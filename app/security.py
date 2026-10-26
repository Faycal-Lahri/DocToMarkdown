"""
==============================================================================
DocToMarkdown - Module de Sécurité et Validation (app/security.py)
==============================================================================

Ce module est le rempart de sécurité de l'application contre les attaques
courantes liées aux fichiers téléversés :
1. Déni de service par saturation mémoire : Streaming direct sur disque par blocs
   de 1 Mo sans jamais charger le fichier complet en RAM.
2. Déni de service par saturation disque : Interruption immédiate du flux d'upload
   si la taille cumulée dépasse MAX_FILE_SIZE_BYTES.
3. Usurpation de type de fichier : Vérification des octets magiques (Magic Bytes)
   sur les premiers octets du fichier, et non pas seulement sur l'extension.
4. Attaques par bombe de décompression (Zip-Bomb) : Les fichiers Word (.docx)
   et PowerPoint (.pptx) sont des archives ZIP. Nous vérifions le ratio de compression,
   la taille totale décompressée et le nombre d'entrées avant tout traitement.
5. Path Traversal : Nettoyage strict des noms de fichiers pour empêcher l'écriture
   ou l'accès à des fichiers en dehors des répertoires prévus (ex: "../../etc/passwd").
6. Rate Limiting par IP : Limitation du nombre de requêtes par minute par client.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
import zipfile
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


# ==============================================================================
# Exceptions spécifiques de sécurité
# ==============================================================================


class SecurityError(Exception):
    """Exception de base pour les violations de sécurité."""

    pass


class FileTooLargeError(SecurityError):
    """Levée quand un fichier dépasse la taille maximale autorisée."""

    pass


class InvalidFileTypeError(SecurityError):
    """Levée quand le type réel (magic bytes) ne correspond pas aux formats admis."""

    pass


class ZipBombDetectedError(SecurityError):
    """Levée lorsqu'une archive ZIP dépasse les seuils de compression sécurisés."""

    pass


class CorruptedFileError(SecurityError):
    """Levée lorsqu'un fichier est illisible ou corrompu."""

    pass


class EncryptedPdfError(SecurityError):
    """Levée lorsqu'un document PDF est verrouillé par un mot de passe."""

    pass


# ==============================================================================
# Signatures Magiques (Magic Bytes)
# ==============================================================================
# Pourquoi les magic bytes ?
# Un attaquant peut renommer un exécutable ou un script malveillant en "rapport.pdf".
# La vérification des premiers octets du fichier permet de s'assurer de sa véritable
# nature binaire de manière inviolable.

MAGIC_PDF: bytes = b"%PDF"
MAGIC_ZIP: bytes = b"PK\x03\x04"
MAGIC_ZIP_EMPTY: bytes = b"PK\x05\x06"
MAGIC_ZIP_SPANNED: bytes = b"PK\x07\x08"


def detect_file_format_by_magic_bytes(file_path: Path) -> str:
    """
    Détecte le format réel d'un fichier en lisant ses premiers octets (magic bytes).

    Paramètres:
        file_path: Chemin absolu vers le fichier stocké sur disque.

    Retourne:
        L'une des chaînes : 'pdf', 'zip' (docx/pptx), ou lève une InvalidFileTypeError.
    """
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise CorruptedFileError("Le fichier téléversé est vide ou introuvable.")

    with open(file_path, "rb") as f:
        header = f.read(16)

    # 1. Détection PDF : Commence par %PDF- (ex: %PDF-1.4, %PDF-1.7)
    if header.startswith(MAGIC_PDF):
        return "pdf"

    # 2. Détection ZIP (DOCX / PPTX) :
    # Les formats Office Open XML (docx, pptx) sont structurellement des conteneurs ZIP.
    if header.startswith((MAGIC_ZIP, MAGIC_ZIP_EMPTY, MAGIC_ZIP_SPANNED)):
        return "zip"

    # Si la signature ne correspond à aucun format autorisé
    hex_preview = header[:8].hex()
    logger.warning("Fichier rejeté : signature magique inconnue (%s)", hex_preview)
    raise InvalidFileTypeError(
        f"Format de fichier non reconnu ou non supporté (signature : 0x{hex_preview}). "
        "Seuls les fichiers PDF, Word (.docx) et PowerPoint (.pptx) sont acceptés."
    )


# ==============================================================================
# Protection Anti Zip-Bomb
# ==============================================================================


def validate_zip_archive_safety(file_path: Path) -> None:
    """
    Inspecte une archive ZIP (docx/pptx) pour s'assurer qu'il ne s'agit pas
    d'une bombe de décompression (zip-bomb).

    Vérifications effectuées :
    1. Nombre total d'entrées (limité à settings.ZIP_BOMB_MAX_ENTRIES).
    2. Taille cumulée décompressée (limitée à settings.ZIP_BOMB_MAX_DECOMPRESSED_BYTES).
    3. Ratio de compression global (décompressé / compressé <= settings.ZIP_BOMB_MAX_RATIO).

    Paramètres:
        file_path: Chemin du fichier zip/docx/pptx sur disque.

    Lève:
        ZipBombDetectedError: Si l'archive viole un seuil de sécurité.
        CorruptedFileError: Si l'archive est corrompue.
    """
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            infolist = zf.infolist()
            total_entries = len(infolist)

            if total_entries > settings.ZIP_BOMB_MAX_ENTRIES:
                logger.warning(
                    "Alerte Zip-Bomb : trop d'entrées (%d > %d) dans %s",
                    total_entries,
                    settings.ZIP_BOMB_MAX_ENTRIES,
                    file_path.name,
                )
                raise ZipBombDetectedError(
                    f"Archive suspecte : contient {total_entries} fichiers "
                    f"(limite autorisée : {settings.ZIP_BOMB_MAX_ENTRIES})."
                )

            total_uncompressed = 0
            total_compressed = 0

            for info in infolist:
                # Anti-traversal interne à l'archive
                if ".." in info.filename or info.filename.startswith(("/", "\\")):
                    raise ZipBombDetectedError(f"Nom d'entrée suspect dans l'archive : '{info.filename}'")

                total_uncompressed += info.file_size
                total_compressed += info.compress_size

                if total_uncompressed > settings.ZIP_BOMB_MAX_DECOMPRESSED_BYTES:
                    logger.warning(
                        "Alerte Zip-Bomb : taille décompressée dépassée (%d octets) dans %s",
                        total_uncompressed,
                        file_path.name,
                    )
                    raise ZipBombDetectedError(
                        "Archive suspecte : la taille décompressée dépasse la limite de sécurité."
                    )

            # Vérification du ratio de compression
            if total_compressed > 0:
                ratio = total_uncompressed / total_compressed
                if ratio > settings.ZIP_BOMB_MAX_RATIO and total_uncompressed > 50 * 1024 * 1024:
                    logger.warning("Alerte Zip-Bomb : ratio anormalement élevé (%.2f:1)", ratio)
                    raise ZipBombDetectedError(f"Archive suspecte : ratio de compression excessif ({ratio:.1f}:1).")

    except zipfile.BadZipFile as e:
        logger.error("Archive ZIP corrompue : %s", e)
        raise CorruptedFileError("Le fichier Word ou PowerPoint est corrompu ou invalide.") from e


# ==============================================================================
# Nettoyage et Sanitization des noms de fichiers
# ==============================================================================


def sanitize_filename(filename: str) -> str:
    """
    Nettoie un nom de fichier fourni par l'utilisateur pour éviter les attaques
    de type Path Traversal (ex: '../../etc/passwd' ou '..\\windows\\system32').

    Règles appliquées :
    - Extraction du seul nom de base (suppression de tout chemin relatif ou absolu).
    - Remplacement des caractères interdits par un tiret bas '_'.
    - Tronquage à 100 caractères maximum pour éviter les noms anormalement longs.

    Paramètres:
        filename: Nom de fichier brut soumis par le client.

    Retourne:
        Nom de fichier sécurisé et utilisable sans risque.
    """
    if not filename:
        return "document"

    # Extraction du nom de base (compatible Windows et Unix)
    clean_name = Path(filename).name

    # Remplacement des caractères interdits ou problématiques
    clean_name = re.sub(r'[\\/*?:"<>| \t\n\r]+', "_", clean_name)

    # Suppression des points initiaux (fichiers cachés unix)
    clean_name = clean_name.lstrip(".")

    if not clean_name:
        clean_name = "document"

    # Limitation de la longueur
    if len(clean_name) > 100:
        stem = Path(clean_name).stem[:80]
        suffix = Path(clean_name).suffix[:20]
        clean_name = f"{stem}{suffix}"

    return clean_name


def generate_unique_storage_filename(original_filename: str) -> tuple[str, str]:
    """
    Génère un identifiant unique (UUID) pour le stockage sur disque afin
    d'éviter toute collision de fichiers et tout risque d'écrasement.

    Retourne:
        Tuple (safe_original_name, storage_filename_with_uuid)
    """
    safe_name = sanitize_filename(original_filename)
    extension = Path(safe_name).suffix.lower()
    unique_id = uuid.uuid4().hex
    storage_name = f"{unique_id}{extension}"
    return safe_name, storage_name


# ==============================================================================
# Écriture en Streaming par Blocs (Chunked Streaming Upload)
# ==============================================================================


async def save_stream_to_disk(
    stream: AsyncGenerator[bytes, None],
    destination_path: Path,
    max_size_bytes: int = settings.MAX_FILE_SIZE_BYTES,
    chunk_size_bytes: int = settings.STREAM_CHUNK_SIZE_BYTES,
) -> int:
    """
    Écrit un flux asynchrone de données directement sur le disque par blocs
    de 1 Mo (chunked streaming), en surveillant la taille cumulée en temps réel.

    Pourquoi cette méthode ?
    Si un utilisateur envoie un fichier de 500 Mo, charger ce fichier d'un coup
    dans la mémoire vive (RAM) de Python consommerait beaucoup de ressources et
    pourrait provoquer un Out Of Memory (OOM) en cas de requêtes simultanées.
    En écrivant par blocs de 1 Mo, l'empreinte mémoire reste constante (< 5 Mo)
    quelle que soit la taille du document.

    Si la taille totale dépasse la limite autorisée, le streaming est interrompu
    immédiatement et le fichier partiel est supprimé du disque.

    Paramètres:
        stream: Générateur asynchrone fournissant les octets au fur et à mesure.
        destination_path: Chemin du fichier de destination sur disque.
        max_size_bytes: Taille maximale admise en octets.
        chunk_size_bytes: Taille de chaque bloc écrit.

    Retourne:
        Le nombre total d'octets écrits sur disque.

    Lève:
        FileTooLargeError: Si la taille dépasse max_size_bytes.
    """
    bytes_written = 0
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(destination_path, "wb") as out_file:
            async for chunk in stream:
                if not chunk:
                    continue

                bytes_written += len(chunk)

                if bytes_written > max_size_bytes:
                    logger.warning(
                        "Téléversement stoppé : le fichier dépasse la limite autorisée (%d > %d octets)",
                        bytes_written,
                        max_size_bytes,
                    )
                    raise FileTooLargeError(
                        f"Le fichier dépasse la taille maximale autorisée ({max_size_bytes // (1024 * 1024)} Mo)."
                    )

                out_file.write(chunk)

        # Si le fichier final est vide
        if bytes_written == 0:
            raise CorruptedFileError("Le fichier téléversé est totalement vide (0 octet).")

        return bytes_written

    except Exception:
        # En cas d'erreur ou d'interruption, nettoyage immédiat du fichier partiel
        if destination_path.exists():
            try:
                destination_path.unlink()
            except OSError as err:
                logger.error("Impossible de supprimer le fichier partiel : %s", err)
        raise


# ==============================================================================
# Rate Limiting simple par IP (en mémoire)
# ==============================================================================


@dataclass
class IPRateRecord:
    timestamps: list[float]


class SimpleIPRateLimiter:
    """
    Limiteur de débit simple basé sur une fenêtre glissante en mémoire par IP.
    Permet de protéger l'API contre les abus et le spam sans nécessiter
    une dépendance externe lourde telle que Redis.
    """

    def __init__(self, max_requests: int = settings.RATE_LIMIT_REQUESTS_PER_MINUTE, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._records: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, ip_address: str) -> bool:
        """
        Vérifie si une requête depuis l'adresse IP spécifiée est autorisée.
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Nettoyage des timestamps expirés pour cette IP
        timestamps = self._records[ip_address]
        # Conserver uniquement les requêtes dans la fenêtre active
        self._records[ip_address] = [t for t in timestamps if t > window_start]

        if len(self._records[ip_address]) >= self.max_requests:
            return False

        self._records[ip_address].append(now)
        return True


# Instance singleton du rate limiter
rate_limiter = SimpleIPRateLimiter()
