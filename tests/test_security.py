"""
==============================================================================
DocToMarkdown - Tests de Sécurité et Robustesse (tests/test_security.py)
==============================================================================

Ces tests valident les protections de l'application contre les attaques courantes :
1. Falsification d'extension (Magic Bytes).
2. Attaques par traversée de répertoire (Path Traversal).
3. Bombes de décompression (Zip-Bombs).
4. Fichiers vides ou corrompus.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import pytest

from app.security import (
    CorruptedFileError,
    InvalidFileTypeError,
    ZipBombDetectedError,
    detect_file_format_by_magic_bytes,
    sanitize_filename,
    validate_zip_archive_safety,
)


@pytest.fixture
def temp_workspace():
    """Crée un répertoire temporaire pour les fichiers de tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


def test_sanitize_filename_prevents_path_traversal():
    """
    Vérifie que les tentatives d'injection de chemins (Path Traversal)
    sont neutralisées par la fonction de nettoyage.
    """
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\Windows\\System32\\cmd.exe") == "cmd.exe"
    assert sanitize_filename("../../../rapport.pdf") == "rapport.pdf"
    assert sanitize_filename("document<script>.pdf") == "document_script_.pdf"
    assert sanitize_filename("") == "document"


def test_detect_magic_bytes_rejects_spoofed_file(temp_workspace: Path):
    """
    Vérifie qu'un fichier binaire malveillant renommé avec l'extension '.pdf'
    mais sans signature magique %PDF est immédiatement rejeté.
    """
    fake_pdf = temp_workspace / "fake_document.pdf"
    with open(fake_pdf, "wb") as f:
        # Octets arbitraires (ex: en-tête d'exécutable Windows MZ ou script shell)
        f.write(b"MZ\x90\x00\x03\x00\x00\x00malicious_binary_content")

    with pytest.raises(InvalidFileTypeError):
        detect_file_format_by_magic_bytes(fake_pdf)


def test_empty_file_raises_corrupted_error(temp_workspace: Path):
    """
    Vérifie qu'un fichier de 0 octet déclenche une CorruptedFileError.
    """
    empty_file = temp_workspace / "empty.pdf"
    empty_file.touch()

    with pytest.raises(CorruptedFileError):
        detect_file_format_by_magic_bytes(empty_file)


def test_zip_bomb_detection(temp_workspace: Path):
    """
    Vérifie qu'une archive contenant un nombre excessif d'entrées
    ou une tentative de path traversal interne est détectée et bloquée.
    """
    # 1. Test entrée avec path traversal interne
    malicious_zip = temp_workspace / "malicious.docx"
    with zipfile.ZipFile(malicious_zip, "w") as zf:
        zf.writestr("../evil.txt", "contenu malveillant")

    with pytest.raises(ZipBombDetectedError):
        validate_zip_archive_safety(malicious_zip)
