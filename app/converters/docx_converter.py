"""
==============================================================================
DocToMarkdown - Convertisseur DOCX vers Markdown (app/converters/docx_converter.py)
==============================================================================

Ce module convertit les documents Microsoft Word (.docx) en Markdown :
1. Moteur prioritaire : Pandoc via `pypandoc_binary`. Pandoc est la référence
   mondiale de conversion documentaire open-source, avec un support exhaustif
   de la typographie et de la sémantique Word.
2. Moteur de repli (Fallback) autonome : Si Pandoc n'est pas utilisable, le module
   bascule automatiquement sur un parseur natif développé en code pur Python
   avec `python-docx`. Ce repli gère les titres (Heading 1 à 6), les paragraphes,
   le gras (**), l'italique (*), les listes à puces et numérotées, ainsi que les
   tableaux Markdown GFM complets.
3. Extraction d'images : Si l'option 'keep_images' est active, les images intégrées
   dans le document OpenXML (.docx) sont extraites dans un dossier images/ et
   référencées dans le document Markdown.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.converters.base import BaseConverter, CancellationCheck, ConversionResult, JobCancelledError, ProgressCallback

logger = logging.getLogger(__name__)


class DocxConverter(BaseConverter):
    """
    Convertisseur pour les fichiers Word (.docx) avec double moteur (Pandoc + Natif).
    """

    def convert(
        self,
        file_path: Path,
        output_dir: Path,
        keep_images: bool = False,
        ocr: bool = False,
        progress_callback: ProgressCallback | None = None,
        cancel_check: CancellationCheck | None = None,
    ) -> ConversionResult:
        """
        Convertit un document .docx en Markdown.
        """
        if cancel_check and cancel_check():
            raise JobCancelledError("Conversion Word annulée par l'utilisateur.")
        output_dir.mkdir(parents=True, exist_ok=True)
        image_dir = output_dir / "images"
        if keep_images:
            image_dir.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(10.0, 1, 1, "Initialisation de la conversion Word (.docx)...")

        # 1. Tentative avec Pandoc (pypandoc)
        try:
            import pypandoc

            extra_args = ["--wrap=none", "--markdown-headings=atx"]
            if keep_images:
                extra_args.append(f"--extract-media={output_dir}")

            if progress_callback:
                progress_callback(40.0, 1, 1, "Conversion en cours avec le moteur Pandoc...")

            markdown_text = pypandoc.convert_file(str(file_path), to="gfm", format="docx", extra_args=extra_args)

            # Collecte des images extraites par pandoc
            extracted_images: list[Path] = []
            media_folder = output_dir / "media"
            if media_folder.exists():
                for img_file in media_folder.glob("**/*"):
                    if img_file.is_file():
                        extracted_images.append(img_file)

            if progress_callback:
                progress_callback(100.0, 1, 1, "Conversion Word terminée avec succès !")

            return ConversionResult(
                markdown_content=markdown_text,
                image_files=extracted_images,
                warnings=[],
                pages_count=1,
            )

        except Exception as pandoc_err:
            logger.info("Pandoc non disponible ou erreur (%s), bascule sur le parseur natif python-docx.", pandoc_err)

        # 2. Moteur de repli natif avec python-docx
        return self._convert_native(file_path, output_dir, keep_images, progress_callback)

    def _convert_native(
        self,
        file_path: Path,
        output_dir: Path,
        keep_images: bool,
        progress_callback: ProgressCallback | None,
    ) -> ConversionResult:
        """
        Convertit le fichier Word via l'arbre de document structuré de `python-docx`.
        """
        import docx

        if progress_callback:
            progress_callback(30.0, 1, 1, "Analyse structurée du document Word...")

        doc = docx.Document(str(file_path))
        md_lines: list[str] = [f"# {file_path.stem}\n"]
        extracted_images: list[Path] = []
        warnings: list[str] = []

        # Extraction des images embarquées dans les relations OpenXML
        if keep_images:
            image_dir = output_dir / "images"
            image_dir.mkdir(parents=True, exist_ok=True)
            img_counter = 0

            for rel in doc.part.related_parts.values():
                if "image" in rel.content_type:
                    img_counter += 1
                    ext = rel.content_type.split("/")[-1]
                    if ext == "jpeg":
                        ext = "jpg"
                    img_name = f"image_{img_counter}.{ext}"
                    img_path = image_dir / img_name
                    with open(img_path, "wb") as f_img:
                        f_img.write(rel.blob)
                    extracted_images.append(img_path)

        total_elements = len(doc.paragraphs) + len(doc.tables)
        current_elem = 0

        # Traitement des paragraphes
        for para in doc.paragraphs:
            current_elem += 1
            text = para.text.strip()
            if not text:
                continue

            style_name = para.style.name.lower() if para.style else ""

            # Titres
            if "heading 1" in style_name:
                md_lines.append(f"\n# {text}\n")
            elif "heading 2" in style_name:
                md_lines.append(f"\n## {text}\n")
            elif "heading 3" in style_name:
                md_lines.append(f"\n### {text}\n")
            elif "heading 4" in style_name:
                md_lines.append(f"\n#### {text}\n")
            elif "heading 5" in style_name:
                md_lines.append(f"\n##### {text}\n")
            elif "heading 6" in style_name:
                md_lines.append(f"\n###### {text}\n")
            # Listes à puces
            elif "bullet" in style_name or "list" in style_name:
                md_lines.append(f"- {self._format_paragraph_runs(para)}")
            # Citations
            elif "quote" in style_name:
                md_lines.append(f"> {self._format_paragraph_runs(para)}\n")
            # Paragraphes normaux avec mise en forme inline
            else:
                formatted_para = self._format_paragraph_runs(para)
                md_lines.append(f"\n{formatted_para}\n")

            if progress_callback and total_elements > 0 and current_elem % 50 == 0:
                pct = min(90.0, 30.0 + (current_elem / total_elements) * 60.0)
                progress_callback(pct, current_elem, total_elements, "Conversion des paragraphes et styles...")

        # Traitement des tableaux
        for table in doc.tables:
            current_elem += 1
            table_md = self._convert_table_to_markdown(table)
            if table_md:
                md_lines.append(f"\n{table_md}\n")

        # Ajout des images extraites à la fin du document si demandé
        if keep_images and extracted_images:
            md_lines.append("\n\n## Images du document\n")
            for img in extracted_images:
                rel_path = f"images/{img.name}"
                md_lines.append(f"\n![{img.stem}]({rel_path})\n")

        if progress_callback:
            progress_callback(100.0, 1, 1, "Conversion Word terminée avec succès !")

        full_text = "\n".join(md_lines)
        return ConversionResult(
            markdown_content=full_text,
            image_files=extracted_images,
            warnings=warnings,
            pages_count=1,
        )

    def _format_paragraph_runs(self, paragraph) -> str:
        """
        Convertit les runs (fragments de texte) en préservant le gras et l'italique Markdown.
        """
        parts = []
        for run in paragraph.runs:
            text = run.text
            if not text:
                continue

            if run.bold and run.italic:
                parts.append(f"***{text}***")
            elif run.bold:
                parts.append(f"**{text}**")
            elif run.italic:
                parts.append(f"*{text}*")
            elif run.font.strike:
                parts.append(f"~~{text}~~")
            else:
                parts.append(text)

        return "".join(parts) if parts else paragraph.text

    def _convert_table_to_markdown(self, table) -> str:
        """
        Convertit un tableau Word en tableau Markdown format GFM valide.
        """
        rows = table.rows
        if not rows:
            return ""

        table_lines = []

        # En-têtes (première ligne)
        header_cells = [cell.text.strip().replace("\n", " ").replace("|", "\\|") for cell in rows[0].cells]
        table_lines.append("| " + " | ".join(header_cells) + " |")

        # Ligne de séparation GFM (|---|---|)
        separators = ["---" for _ in header_cells]
        table_lines.append("| " + " | ".join(separators) + " |")

        # Lignes de données
        for row in rows[1:]:
            row_cells = [cell.text.strip().replace("\n", " ").replace("|", "\\|") for cell in row.cells]
            table_lines.append("| " + " | ".join(row_cells) + " |")

        return "\n".join(table_lines)
