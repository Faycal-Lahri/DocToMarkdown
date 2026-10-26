"""
==============================================================================
DocToMarkdown - Fabrique de Convertisseurs (app/converters/factory.py)
==============================================================================

Ce module implémente le patron de conception Fabrique (Factory Pattern) :
1. Découplage de la sélection du moteur : Le reste de l'application demande
   simplement un convertisseur pour un chemin de fichier donné, sans savoir
   comment le format est analysé.
2. Détection binaire sécurisée :
   - Pour les PDF : vérification de la signature magique %PDF.
   - Pour les archives ZIP : inspection du fichier binaire et des métadonnées
     internes OpenXML ([Content_Types].xml) ou de l'extension pour distinguer
     un document Word (.docx) d'une présentation PowerPoint (.pptx).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from app.converters.base import BaseConverter
from app.converters.docx_converter import DocxConverter
from app.converters.pdf_converter import PdfConverter
from app.converters.pptx_converter import PptxConverter
from app.security import (
    InvalidFileTypeError,
    detect_file_format_by_magic_bytes,
    validate_zip_archive_safety,
)

logger = logging.getLogger(__name__)


def get_converter(file_path: Path) -> BaseConverter:
    """
    Sélectionne et instancie le bon convertisseur selon la nature réelle du fichier.

    Paramètres:
        file_path: Chemin du document stocké sur disque.

    Retourne:
        Une instance de PdfConverter, DocxConverter ou PptxConverter.

    Lève:
        InvalidFileTypeError: Si le format n'est pas reconnu ou non supporté.
        ZipBombDetectedError: Si un fichier zip/docx/pptx est suspect.
    """
    # 1. Vérification par les magic bytes binaires
    raw_kind = detect_file_format_by_magic_bytes(file_path)

    if raw_kind == "pdf":
        return PdfConverter()

    if raw_kind == "zip":
        # Contrôle anti-bombe de décompression avant tout accès
        validate_zip_archive_safety(file_path)

        # Distinction fine entre DOCX et PPTX par inspection du manifest OpenXML
        extension = file_path.suffix.lower()
        if extension == ".docx":
            return DocxConverter()
        elif extension == ".pptx":
            return PptxConverter()

        # Si l'extension n'est pas explicite, inspection interne de l'archive
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                namelist = zf.namelist()
                if any(name.startswith("word/") for name in namelist):
                    return DocxConverter()
                if any(name.startswith("ppt/") for name in namelist):
                    return PptxConverter()
        except Exception as e:
            logger.error("Erreur d'inspection interne de l'archive : %s", e)

        raise InvalidFileTypeError(
            "Le fichier est une archive ZIP valide mais n'est ni un document Word (.docx) "
            "ni une présentation PowerPoint (.pptx) reconnue."
        )

    raise InvalidFileTypeError("Format de fichier non pris en charge.")
