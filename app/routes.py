"""
==============================================================================
DocToMarkdown - Routes et Contrôleurs de l'API REST (app/routes.py)
==============================================================================

Ce module expose tous les points de terminaison (endpoints) de l'application :
1. POST /api/convert : Réception multipart avec streaming direct sur disque par blocs
   de 1 Mo (zéro saturation mémoire) et lancement immédiat du job en tâche de fond.
2. GET /api/jobs/{job_id} : Récupération de l'état (polling de repli).
3. GET /api/jobs/{job_id}/events : Flux temps réel Server-Sent Events (SSE).
4. GET /api/jobs/{job_id}/download : Téléchargement du résultat (.md direct ou .zip complet).
5. GET /api/jobs/{job_id}/preview : Aperçu textuel du Markdown pour affichage web
   (tronqué proprement à 200 Ko pour préserver la fluidité du navigateur).
6. GET /api/health : Vérification de la santé et métriques système.
7. DELETE /api/jobs/{job_id} : Annulation ou nettoyage immédiat.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from app.config import settings
from app.converters.factory import get_converter
from app.jobs import JobStatus, job_manager
from app.security import (
    CorruptedFileError,
    EncryptedPdfError,
    FileTooLargeError,
    InvalidFileTypeError,
    ZipBombDetectedError,
    generate_unique_storage_filename,
    rate_limiter,
    save_stream_to_disk,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Conversion"])


# ==============================================================================
# Tâche d'arrière-plan de conversion
# ==============================================================================


async def _run_conversion_in_background(job_id: str) -> None:
    """
    Exécute la conversion de manière totalement asynchrone pour ne jamais
    bloquer le serveur web ni subir d'interruption HTTP.
    """
    job = job_manager.get_job(job_id)
    if not job:
        logger.error("Job [%s] introuvable au démarrage de la tâche de fond", job_id)
        return

    def _sync_progress_callback(percent: float, cur_page: int, tot_pages: int, message: str) -> None:
        """
        Callback synchrone appelé par les convertisseurs (qui tournent dans un thread ou process).
        Transmet directement la progression au gestionnaire de jobs.
        """
        job_manager.update_job(
            job_id,
            progress=percent,
            current_page=cur_page,
            total_pages=tot_pages,
            current_step=message,
        )

    try:
        job_manager.update_job(
            job_id, status=JobStatus.RUNNING, progress=5.0, current_step="Initialisation du convertisseur..."
        )

        # 1. Sélection automatique du moteur de conversion
        converter = get_converter(job.storage_path)

        # 2. Exécution de la conversion dans un thread séparé (pour ne pas bloquer l'event loop)
        result = await asyncio.to_thread(
            converter.convert,
            file_path=job.storage_path,
            output_dir=job.output_dir,
            keep_images=job.keep_images,
            ocr=job.ocr,
            progress_callback=_sync_progress_callback,
        )

        # 3. Zéro persistance disque : Suppression immédiate du fichier source téléversé
        if job.storage_path and job.storage_path.exists():
            try:
                job.storage_path.unlink(missing_ok=True)
                logger.info("Fichier source temporaire purgé du disque : %s", job.storage_path.name)
            except Exception as clean_err:
                logger.debug("Nettoyage source : %s", clean_err)

        # 4. Préparation de l'aperçu textuel
        content_bytes = result.markdown_content.encode("utf-8")
        is_truncated = len(content_bytes) > settings.MAX_PREVIEW_BYTES
        if is_truncated:
            preview_bytes = content_bytes[: settings.MAX_PREVIEW_BYTES]
            preview_text = preview_bytes.decode("utf-8", errors="ignore")
            preview_text += (
                f"\n\n\n> ⚠️ **Aperçu tronqué à {settings.MAX_PREVIEW_BYTES // 1024} Ko.** "
                "Téléchargez le fichier complet (.md ou .zip) pour accéder à l'intégralité du document."
            )
        else:
            preview_text = result.markdown_content

        clean_stem = Path(job.original_filename).stem

        # 5. Création de l'archive ZIP 100% en mémoire si des images ont été extraites
        zip_bytes: bytes | None = None
        has_images = len(result.image_files) > 0

        if has_images or job.keep_images:
            import io

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Ajout du markdown en mémoire
                zf.writestr(f"{clean_stem}.md", result.markdown_content)
                # Ajout des images
                for img_path in result.image_files:
                    if img_path.exists():
                        zf.write(img_path, arcname=f"images/{img_path.name}")
            zip_bytes = zip_buffer.getvalue()

        # 6. Zéro persistance disque : purge immédiate du dossier output temporaire
        if job.output_dir and job.output_dir.exists():
            shutil.rmtree(job.output_dir, ignore_errors=True)

        # 7. Finalisation du job en mémoire vive
        job_manager.update_job(
            job_id,
            status=JobStatus.DONE,
            progress=100.0,
            current_step="Conversion terminée avec succès !",
            warnings=result.warnings,
            markdown_content=result.markdown_content,
            zip_bytes=zip_bytes,
            preview_text=preview_text,
            is_preview_truncated=is_truncated,
            extracted_images_count=len(result.image_files),
        )
        logger.info("Job [%s] converti en mémoire (Zero-Disk) avec succès (%s)", job_id, job.original_filename)

    except EncryptedPdfError as e:
        logger.warning("Job [%s] en échec (PDF protégé) : %s", job_id, e)
        job_manager.update_job(
            job_id,
            status=JobStatus.ERROR,
            error_message="Ce document PDF est protégé par mot de passe. Veuillez le déverrouiller avant conversion.",
        )
    except (InvalidFileTypeError, ZipBombDetectedError, CorruptedFileError, FileTooLargeError) as e:
        logger.warning("Job [%s] en échec de validation : %s", job_id, e)
        job_manager.update_job(job_id, status=JobStatus.ERROR, error_message=str(e))
    except Exception as exc:
        logger.exception("Erreur inattendue lors de la conversion du job [%s] : %s", job_id, exc)
        job_manager.update_job(
            job_id,
            status=JobStatus.ERROR,
            error_message="Une erreur inattendue s'est produite lors de la conversion du document.",
        )
    finally:
        import gc
        gc.collect()


# ==============================================================================
# Endpoints de l'API
# ==============================================================================


@router.post("/convert", status_code=status.HTTP_202_ACCEPTED)
async def upload_and_convert_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    keep_images: bool = Form(default=False),
    ocr: bool = Form(default=False),
):
    """
    Reçoit un ou plusieurs fichiers en streaming multipart, initialise les jobs
    et lance les conversions en arrière-plan.

    Retourne:
        { "job_ids": ["..."], "job_id": "premier_job_id" }
    """
    # 1. Vérification du Rate Limiting par IP
    client_ip = request.client.host if request.client else "127.0.0.1"
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Trop de requêtes. Veuillez patienter une minute avant de téléverser à nouveau.",
        )

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucun fichier fourni dans la requête.")

    job_ids: list[str] = []

    for file in files:
        original_filename = file.filename or "document"
        safe_name, storage_name = generate_unique_storage_filename(original_filename)

        storage_path = settings.UPLOAD_DIR / storage_name
        job_id = Path(storage_name).stem
        output_dir = settings.OUTPUT_DIR / job_id

        # 2. Écriture en streaming par blocs de 1 Mo directement sur disque
        async def _file_stream():
            while True:
                chunk = await file.read(settings.STREAM_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                yield chunk

        try:
            await save_stream_to_disk(
                stream=_file_stream(),
                destination_path=storage_path,
                max_size_bytes=settings.MAX_FILE_SIZE_BYTES,
                chunk_size_bytes=settings.STREAM_CHUNK_SIZE_BYTES,
            )
        except FileTooLargeError as e:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(e))
        except CorruptedFileError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
        except Exception as e:
            logger.error("Erreur streaming upload : %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur lors de l'enregistrement."
            )

        # 3. Création du Job
        job_manager.create_job(
            job_id=job_id,
            original_filename=safe_name,
            storage_path=storage_path,
            output_dir=output_dir,
            keep_images=keep_images,
            ocr=ocr,
        )
        job_ids.append(job_id)

        # 4. Lancement de la conversion en tâche asynchrone non-bloquante
        background_tasks.add_task(_run_conversion_in_background, job_id)

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job_ids": job_ids,
            "job_id": job_ids[0],
            "count": len(job_ids),
            "message": "Conversion initialisée avec succès.",
        },
    )


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """
    Renvoie l'état courant d'un job (pour le polling de repli).
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifiant de job introuvable ou expiré.")
    return JSONResponse(content=job.to_dict())


@router.get("/jobs/{job_id}/events")
async def get_job_sse_events(job_id: str):
    """
    Émet un flux Server-Sent Events (SSE) notifiant la progression en temps réel.
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identifiant de job introuvable ou expiré.")

    return StreamingResponse(
        job_manager.subscribe_events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Pour nginx / reverse proxy
        },
    )


@router.get("/jobs/{job_id}/preview")
async def get_job_preview(job_id: str):
    """
    Renvoie le contenu Markdown pour l'aperçu dans le navigateur.
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job introuvable.")

    if job.status == JobStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=job.error_message or "Erreur de conversion."
        )

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La conversion n'est pas encore terminée.")

    return JSONResponse(
        content={
            "job_id": job_id,
            "filename": job.original_filename,
            "markdown": job.preview_text or "",
            "is_truncated": job.is_preview_truncated,
            "has_images": job.extracted_images_count > 0,
            "warnings": job.warnings,
        }
    )


@router.get("/jobs/{job_id}/download")
async def download_job_result(job_id: str, format: str | None = None):
    """
    Télécharge le résultat de la conversion :
    - Fichier .md direct si format='md' ou s'il n'y a pas d'images.
    - Archive .zip si format='zip' ou si le document contient des images.
    """
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job introuvable.")

    if job.status != JobStatus.DONE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Le document n'est pas encore prêt.")

    clean_stem = Path(job.original_filename).stem

    # 1. Si l'utilisateur demande explicitement le ZIP ou si des images ont été extraites
    if format == "zip" or (job.zip_bytes is not None and format != "md"):
        if job.zip_bytes:
            return Response(
                content=job.zip_bytes,
                media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{clean_stem}.zip"'},
            )
        if job.archive_path and job.archive_path.exists():
            return FileResponse(
                path=job.archive_path,
                filename=f"{clean_stem}.zip",
                media_type="application/zip",
            )

    # 2. Téléchargement direct du fichier Markdown depuis la mémoire vive
    if job.markdown_content is not None:
        return Response(
            content=job.markdown_content.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{clean_stem}.md"'},
        )

    # Repli si fichier encore présent sur disque
    if job.markdown_path and job.markdown_path.exists():
        return FileResponse(
            path=job.markdown_path,
            filename=f"{clean_stem}.md",
            media_type="text/markdown; charset=utf-8",
        )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier de résultat introuvable.")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    """
    Supprime un job et libère l'espace disque immédiatement.
    """
    success = job_manager.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job introuvable.")
    return JSONResponse(content={"message": "Job et fichiers supprimés avec succès."})


@router.get("/health")
async def health_check():
    """
    Endpoint de diagnostic et d'intégrité de l'application.
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "app_name": settings.APP_NAME,
            "version": settings.VERSION,
            "max_workers": settings.MAX_WORKERS,
            "max_file_size_mb": settings.MAX_FILE_SIZE_BYTES // (1024 * 1024),
            "storage_ttl_seconds": settings.STORAGE_TTL_SECONDS,
        }
    )
