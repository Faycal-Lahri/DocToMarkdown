"""
==============================================================================
DocToMarkdown - Interface Abstraite des Convertisseurs (app/converters/base.py)
==============================================================================

Ce fichier définit le contrat d'interface commun à tous les convertisseurs
de documents (PDF, DOCX, PPTX).

Avantages de ce contrat d'interface :
1. Principe d'inversion des dépendances (SOLID - D) : Le reste de l'application
   communique avec l'abstraction BaseConverter sans dépendre des détails d'implémentation.
2. Échangeabilité des moteurs : Possibilité de changer de moteur ou d'ajouter de
   nouveaux formats (ex: ODT, EPUB) sans modifier le code de routage ou les jobs.
3. Callback de progression unifié : Tous les convertisseurs notifient l'état d'avancement
   avec la même signature (pourcentage, page actuelle, total de pages, message descriptif).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConversionResult:
    """
    Conteneur standardisé pour le résultat d'une conversion de document.
    """

    # Contenu Markdown généré en texte brut
    markdown_content: str

    # Liste des chemins vers les images extraites et sauvegardées sur disque
    image_files: list[Path] = field(default_factory=list)

    # Avertissements relevés pendant la conversion (ex: pages scannées, OCR lent)
    warnings: list[str] = field(default_factory=list)

    # Nombre total de pages ou diapositives traitées
    pages_count: int = 1


# Signature du callback de progression :
# (pourcentage: float, page_en_cours: int, total_pages: int, message_etape: str) -> None
ProgressCallback = Callable[[float, int, int, str], None]


class BaseConverter(ABC):
    """
    Classe de base abstraite que tout convertisseur doit implémenter.
    """

    @abstractmethod
    def convert(
        self,
        file_path: Path,
        output_dir: Path,
        keep_images: bool = False,
        ocr: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> ConversionResult:
        """
        Convertit un document en Markdown.

        Paramètres:
            file_path: Chemin du fichier source sur le disque.
            output_dir: Répertoire de destination pour stocker le Markdown et les images.
            keep_images: Si True, extrait les images et génère des liens Markdown.
                         Si False, ignore les images (gain de performance majeur).
            ocr: Si True, applique la reconnaissance optique de caractères (OCR)
                 sur les pages sans texte (plus lent).
            progress_callback: Fonction appelée pour notifier l'avancement.

        Retourne:
            Une instance de ConversionResult.
        """
        pass
