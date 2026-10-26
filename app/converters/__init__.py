"""
Package des convertisseurs de documents vers Markdown.
Regroupe les moteurs de conversion spécialisés (PDF, DOCX, PPTX).
"""

from app.converters.base import BaseConverter, ConversionResult, ProgressCallback
from app.converters.factory import get_converter

__all__ = [
    "BaseConverter",
    "ConversionResult",
    "ProgressCallback",
    "get_converter",
]
