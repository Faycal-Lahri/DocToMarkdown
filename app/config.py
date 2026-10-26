"""
==============================================================================
DocToMarkdown - Module de Configuration Centralisée (app/config.py)
==============================================================================

Ce fichier centralise l'ensemble des constantes, seuils et paramètres système
utilisés dans toute l'application.

Pourquoi ce fichier ?
1. Éviter les "nombres magiques" disséminés dans le code source.
2. Permettre la configuration via des variables d'environnement (12-factor app).
3. Faciliter les tests avec des paramètres ajustables (dossiers temporaires, seuils).
4. Fournir une documentation vivante de chaque réglage technique.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Paramètres globaux de l'application validés via Pydantic.
    Les variables peuvent être surchargées par des variables d'environnement
    au format DTM_<NOM_PARAMETRE>.
    """

    model_config = SettingsConfigDict(env_prefix="DTM_", env_file=".env", extra="ignore")

    # --- Informations générales ---
    APP_NAME: str = "DocToMarkdown"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    # --- Réseaux & Serveur ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Répertoires de stockage temporaire ---
    # Par défaut, les répertoires temporaires sont créés dans le répertoire de travail.
    # Ils sont nettoyés automatiquement par la tâche de fond (cleanup.py).
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    STORAGE_DIR: Path = BASE_DIR / "storage"
    UPLOAD_DIR: Path = STORAGE_DIR / "uploads"
    OUTPUT_DIR: Path = STORAGE_DIR / "outputs"

    # --- Streaming et Limites de Taille de Fichier ---
    # Taille maximale acceptée pour un fichier entrant (500 Mo par défaut).
    # Cela évite le déni de service (DoS) par épuisement d'espace disque.
    MAX_FILE_SIZE_BYTES: int = 500 * 1024 * 1024  # 500 Mo

    # Taille du bloc de streaming (1 Mo).
    # Le fichier est écrit sur disque par morceaux de 1 Mo sans JAMAIS
    # charger l'intégralité du document volumineux en mémoire vive.
    STREAM_CHUNK_SIZE_BYTES: int = 1024 * 1024  # 1 Mo

    # --- Durée de Vie des Fichiers (TTL) ---
    # Durée après laquelle les uploads et conversions sont supprimés du disque.
    # 1800 secondes = 30 minutes.
    STORAGE_TTL_SECONDS: int = 1800

    # Intervalle d'exécution de la boucle de nettoyage en tâche de fond.
    CLEANUP_INTERVAL_SECONDS: int = 60

    # --- Traitement Parallèle Multi-cœurs Éco-Mémoire ---
    # Plafonné à 4 workers maximum pour préserver la mémoire vive (RAM).
    # Spawner 24 processus sous Windows consommait ~3 Go de RAM inutilement.
    # 2 à 4 workers suffisent pour convertir 50 Mo en quelques secondes tout en
    # maintenant l'empreinte mémoire sous les 120 Mo.
    MAX_WORKERS: int = min(4, max(2, (os.cpu_count() or 4) // 2))

    # --- Sécurité Anti Zip-Bomb (DOCX & PPTX) ---
    # Les fichiers .docx et .pptx sont en réalité des archives ZIP compressées.
    # Une zip-bomb est un petit fichier qui se décompresse en plusieurs centaines de Go.
    # Nous limitons donc strictement le ratio et la taille maximale décompressée.
    ZIP_BOMB_MAX_DECOMPRESSED_BYTES: int = 500 * 1024 * 1024  # 500 Mo max décompressé
    ZIP_BOMB_MAX_ENTRIES: int = 10000  # 10 000 fichiers max dans l'archive
    ZIP_BOMB_MAX_RATIO: float = 100.0  # Ratio max décompressé / compressé

    # --- Aperçu Markdown ---
    # Taille maximale renvoyée par l'API pour l'aperçu textuel direct.
    # Au-delà de 200 Ko, le texte est tronqué dans l'aperçu avec une mention claire,
    # afin de ne pas ralentir le navigateur web du client.
    MAX_PREVIEW_BYTES: int = 200 * 1024  # 200 Ko

    # --- Rate Limiting (Protection DoS par IP) ---
    # Nombre maximal de requêtes d'upload acceptées par minute pour une même adresse IP.
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60

    def init_directories(self) -> None:
        """
        Crée les dossiers de stockage temporaire s'ils n'existent pas encore.
        """
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Instance globale unique de la configuration
settings = Settings()
settings.init_directories()
