"""
==============================================================================
DocToMarkdown - Nettoyage Périodique et Rétention (app/cleanup.py)
==============================================================================

Ce module assure la maintenance automatique du système de fichiers :
1. Évitement de la saturation du disque : Tous les fichiers téléversés et les
   résultats de conversion ont une durée de vie limitée (TTL, 30 min par défaut).
2. Tâche de fond asynchrone : Exécutée périodiquement (toutes les 60 secondes)
   sans bloquer le serveur ASGI ni impacter les performances de conversion.
3. Nettoyage d'arrêt : À l'extinction du serveur FastAPI (lifespan shutdown),
   tous les fichiers résiduels peuvent être purgés proprement.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path

from app.config import settings
from app.jobs import job_manager

logger = logging.getLogger(__name__)


def purge_expired_disk_files(directories: list[Path], ttl_seconds: int = settings.STORAGE_TTL_SECONDS) -> int:
    """
    Parcourt les répertoires spécifiés et supprime tous les fichiers ou dossiers
    dont la date de dernière modification (mtime) est antérieure au seuil TTL.

    Paramètres:
        directories: Liste des répertoires à inspecter (uploads, outputs).
        ttl_seconds: Âge maximal toléré en secondes.

    Retourne:
        Le nombre total d'éléments supprimés.
    """
    now = time.time()
    cutoff_time = now - ttl_seconds
    removed_count = 0

    for directory in directories:
        if not directory.exists():
            continue

        try:
            for item in directory.iterdir():
                try:
                    stat = item.stat()
                    # Si l'élément est plus vieux que le seuil de rétention
                    if stat.st_mtime < cutoff_time:
                        if item.is_dir():
                            shutil.rmtree(item, ignore_errors=True)
                            logger.info("Dossier expiré purgé : %s", item.name)
                        else:
                            item.unlink(missing_ok=True)
                            logger.info("Fichier expiré purgé : %s", item.name)
                        removed_count += 1
                except Exception as item_err:
                    logger.warning("Erreur lors de la suppression de %s : %s", item, item_err)
        except Exception as dir_err:
            logger.error("Erreur lors de l'inspection du dossier %s : %s", directory, dir_err)

    return removed_count


def purge_all_temporary_files() -> None:
    """
    Purge immédiatement et sans condition l'ensemble des fichiers temporaires.
    Appelée lors de l'arrêt du serveur pour laisser un environnement propre.
    """
    logger.info("Purge de tous les fichiers temporaires au shutdown...")
    for directory in [settings.UPLOAD_DIR, settings.OUTPUT_DIR]:
        if directory.exists():
            for item in directory.iterdir():
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning("Impossible de purger %s : %s", item, e)


async def background_cleanup_loop(
    interval_seconds: int = settings.CLEANUP_INTERVAL_SECONDS, ttl_seconds: int = settings.STORAGE_TTL_SECONDS
) -> None:
    """
    Boucle infinie exécutée en tâche de fond dans la boucle d'événements asyncio.
    Tous les 'interval_seconds', elle purge les jobs en mémoire et les fichiers
    expirés sur le disque.
    """
    logger.info(
        "Démarrage de la tâche de nettoyage automatique (intervalle: %ds, TTL: %ds)", interval_seconds, ttl_seconds
    )
    while True:
        try:
            await asyncio.sleep(interval_seconds)

            # 1. Nettoyage des jobs en mémoire
            expired_job_ids = job_manager.get_expired_jobs(ttl_seconds)
            for jid in expired_job_ids:
                job_manager.delete_job(jid)

            # 2. Nettoyage orphelin éventuel sur disque
            purge_expired_disk_files([settings.UPLOAD_DIR, settings.OUTPUT_DIR], ttl_seconds)

        except asyncio.CancelledError:
            logger.info("Tâche de nettoyage interrompue (arrêt demandé).")
            break
        except Exception as exc:
            logger.error("Exception imprévue dans la boucle de nettoyage : %s", exc)
