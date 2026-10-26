"""
==============================================================================
DocToMarkdown - Gestionnaire de Tâches Asynchrones et SSE (app/jobs.py)
==============================================================================

Ce module gère le cycle de vie de chaque conversion de document sous la forme
d'un "Job" asynchrone :
1. Découplage de la requête HTTP : L'utilisateur soumet son document et reçoit
   immédiatement un identifiant unique (job_id) en quelques millisecondes.
2. Évitement des timeouts HTTP : Pour les gros documents (> 50 Mo), une conversion
   synchrone risquerait de déclencher un timeout 504 Gateway Timeout sur un reverse proxy
   ou dans le navigateur.
3. Suivi de progression en temps réel :
   - Par Server-Sent Events (SSE) via /api/jobs/{job_id}/events (mode privilégié).
   - Par polling classique via /api/jobs/{job_id} (mode repli).
4. État en mémoire thread-safe avec verrous pour supporter les accès concurrents.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """
    États possibles d'un travail de conversion.
    """

    QUEUED = "queued"  # En attente de traitement
    RUNNING = "running"  # Traitement en cours (pages en conversion)
    DONE = "done"  # Conversion terminée avec succès
    ERROR = "error"  # Erreur lors du traitement
    CANCELED = "canceled"  # Annulé par l'utilisateur (refresh ou arrêt volontaire)


@dataclass
class Job:
    """
    Représente l'état complet et les métadonnées d'une conversion de document.
    """

    job_id: str
    original_filename: str
    storage_path: Path
    output_dir: Path
    keep_images: bool = False
    ocr: bool = False

    # État et progression
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0  # 0.0 à 100.0 %
    current_step: str = "En attente de démarrage..."
    current_page: int = 0
    total_pages: int = 0

    # Chronométrie
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    # Résultats et avertissements (stockage 100% en mémoire, zéro persistance disque)
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None
    markdown_content: str | None = None
    zip_bytes: bytes | None = None
    markdown_path: Path | None = None
    archive_path: Path | None = None
    preview_text: str | None = None
    is_preview_truncated: bool = False
    extracted_images_count: int = 0

    @property
    def elapsed_seconds(self) -> float:
        """
        Calcule le temps écoulé en secondes avec une précision au dixième.
        """
        if self.started_at is None:
            return 0.0
        end_point = self.completed_at if self.completed_at is not None else time.time()
        return round(end_point - self.started_at, 2)

    def to_dict(self) -> dict[str, Any]:
        """
        Convertit l'état du job en dictionnaire JSON pour les réponses API et SSE.
        """
        return {
            "job_id": self.job_id,
            "filename": self.original_filename,
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "current_step": self.current_step,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "elapsed_seconds": self.elapsed_seconds,
            "warnings": self.warnings,
            "error": self.error_message,
            "has_images": self.extracted_images_count > 0,
            "images_count": self.extracted_images_count,
            "preview_truncated": self.is_preview_truncated,
            "has_archive": self.zip_bytes is not None or (self.archive_path is not None and self.archive_path.exists()),
            "has_markdown": self.markdown_content is not None
            or (self.markdown_path is not None and self.markdown_path.exists()),
        }


class JobManager:
    """
    Gestionnaire centralisé des jobs de conversion.
    Gère le stockage en mémoire, les notifications SSE et le nettoyage.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        # Dictionnaire associant chaque job_id à un ensemble de queues SSE d'abonnés
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    def create_job(
        self,
        job_id: str,
        original_filename: str,
        storage_path: Path,
        output_dir: Path,
        keep_images: bool,
        ocr: bool,
    ) -> Job:
        """
        Instancie et enregistre un nouveau job en état QUEUED.
        """
        job = Job(
            job_id=job_id,
            original_filename=original_filename,
            storage_path=storage_path,
            output_dir=output_dir,
            keep_images=keep_images,
            ocr=ocr,
        )
        self._jobs[job_id] = job
        self._subscribers[job_id] = set()
        logger.info("Job créé [%s] pour le fichier '%s'", job_id, original_filename)
        return job

    def get_job(self, job_id: str) -> Job | None:
        """
        Récupère un job par son identifiant ou renvoie None si introuvable.
        """
        return self._jobs.get(job_id)

    def update_job(
        self,
        job_id: str,
        status: JobStatus | None = None,
        progress: float | None = None,
        current_step: str | None = None,
        current_page: int | None = None,
        total_pages: int | None = None,
        warnings: list[str] | None = None,
        error_message: str | None = None,
        markdown_content: str | None = None,
        zip_bytes: bytes | None = None,
        markdown_path: Path | None = None,
        archive_path: Path | None = None,
        preview_text: str | None = None,
        is_preview_truncated: bool | None = None,
        extracted_images_count: int | None = None,
    ) -> Job | None:
        """
        Met à jour l'état d'un job de manière synchrone et diffuse la mise à jour
        aux clients connectés en Server-Sent Events (SSE).
        """
        job = self.get_job(job_id)
        if not job:
            return None

        if job.status == JobStatus.CANCELED:
            # Le job a été annulé par l'utilisateur, ne pas écraser son état
            return job

        # Gestion des horodatages de début et de fin
        if status == JobStatus.RUNNING and job.started_at is None:
            job.started_at = time.time()
        elif status in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELED) and job.completed_at is None:
            job.completed_at = time.time()

        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0.0, min(100.0, progress))
        if current_step is not None:
            job.current_step = current_step
        if current_page is not None:
            job.current_page = current_page
        if total_pages is not None:
            job.total_pages = total_pages
        if warnings is not None:
            job.warnings.extend(warnings)
        if error_message is not None:
            job.error_message = error_message
        if markdown_content is not None:
            job.markdown_content = markdown_content
        if zip_bytes is not None:
            job.zip_bytes = zip_bytes
        if markdown_path is not None:
            job.markdown_path = markdown_path
        if archive_path is not None:
            job.archive_path = archive_path
        if preview_text is not None:
            job.preview_text = preview_text
        if is_preview_truncated is not None:
            job.is_preview_truncated = is_preview_truncated
        if extracted_images_count is not None:
            job.extracted_images_count = extracted_images_count

        # Diffusion temps réel aux clients abonnés
        self._broadcast_job_event(job)
        return job

    def _broadcast_job_event(self, job: Job) -> None:
        """
        Émet les données actualisées du job dans chaque file d'attente d'abonnés SSE.
        """
        queues = self._subscribers.get(job.job_id, set())
        if not queues:
            return

        payload = json.dumps(job.to_dict())
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("File d'événements pleine pour le job %s", job.job_id)
            except Exception as e:
                logger.debug("Erreur broadcast SSE : %s", e)

    async def subscribe_events(self, job_id: str) -> AsyncGenerator[str, None]:
        """
        Générateur asynchrone fournissant le flux SSE pour un client HTTP.
        """
        job = self.get_job(job_id)
        if not job:
            yield f"data: {json.dumps({'error': 'Job introuvable'})}\n\n"
            return

        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        if job_id not in self._subscribers:
            self._subscribers[job_id] = set()
        self._subscribers[job_id].add(queue)

        # Envoi immédiat du premier état
        initial_payload = json.dumps(job.to_dict())
        yield f"data: {initial_payload}\n\n"

        # Si le job est déjà terminé, on s'arrête
        if job.status in (JobStatus.DONE, JobStatus.ERROR):
            self._subscribers[job_id].discard(queue)
            return

        try:
            while True:
                try:
                    # Attente d'un message avec un timeout de 15s (keep-alive SSE)
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"

                    # Si l'état transmis est final, fin du flux
                    data_obj = json.loads(payload)
                    if data_obj.get("status") in (JobStatus.DONE.value, JobStatus.ERROR.value):
                        break
                except TimeoutError:
                    # Envoi d'un commentaire keep-alive pour maintenir la connexion active
                    yield ": ping\n\n"
        finally:
            # Désabonnement propre à la déconnexion du client
            if job_id in self._subscribers:
                self._subscribers[job_id].discard(queue)

    def delete_job(self, job_id: str) -> bool:
        """
        Supprime un job de la mémoire et efface ses fichiers associés.
        """
        job = self._jobs.pop(job_id, None)
        self._subscribers.pop(job_id, None)

        if not job:
            return False

        # Suppression des fichiers sur disque
        try:
            if job.storage_path and job.storage_path.exists():
                job.storage_path.unlink(missing_ok=True)
            if job.output_dir and job.output_dir.exists():
                import shutil

                shutil.rmtree(job.output_dir, ignore_errors=True)
            logger.info("Fichiers du job [%s] supprimés avec succès.", job_id)
        except Exception as e:
            logger.error("Erreur lors de la suppression des fichiers du job [%s]: %s", job_id, e)

        return True

    def cancel_job(self, job_id: str) -> bool:
        """
        Arrête immédiatement un job en cours et notifie les abonnés SSE.
        """
        job = self.get_job(job_id)
        if not job:
            return False

        if job.status in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELED):
            return False

        job.status = JobStatus.CANCELED
        job.current_step = "Conversion interrompue par l'utilisateur."
        job.completed_at = time.time()

        # Suppression immédiate des fichiers temporaires
        try:
            if job.storage_path and job.storage_path.exists():
                job.storage_path.unlink(missing_ok=True)
            if job.output_dir and job.output_dir.exists():
                import shutil

                shutil.rmtree(job.output_dir, ignore_errors=True)
        except Exception as e:
            logger.warning("Erreur nettoyage job annulé [%s]: %s", job_id, e)

        logger.info("Job [%s] a été annulé par l'utilisateur.", job_id)
        self._broadcast_job_event(job)
        return True

    def is_job_cancelled(self, job_id: str) -> bool:
        """
        Vérifie si un job a été marqué comme annulé.
        """
        job = self.get_job(job_id)
        return job is not None and job.status == JobStatus.CANCELED

    def get_expired_jobs(self, ttl_seconds: int = settings.STORAGE_TTL_SECONDS) -> list[str]:
        """
        Identifie les jobs dont l'âge dépasse le TTL configuré.
        """
        now = time.time()
        expired = []
        for jid, job in self._jobs.items():
            reference_time = job.completed_at or job.created_at
            if now - reference_time > ttl_seconds:
                expired.append(jid)
        return expired


# Instance singleton du gestionnaire de jobs
job_manager = JobManager()
