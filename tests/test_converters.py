"""
==============================================================================
DocToMarkdown - Tests Unitaires des Convertisseurs (tests/test_converters.py)
==============================================================================

Ces tests créent dynamiquement de petits fichiers PDF, Word et PowerPoint valides
en mémoire et vérifient que chaque convertisseur produit le Markdown attendu.
Aucun fichier binaire externe n'est requis.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import docx
import pymupdf
import pytest
from pptx import Presentation

from app.converters.docx_converter import DocxConverter
from app.converters.pdf_converter import PdfConverter
from app.converters.pptx_converter import PptxConverter


@pytest.fixture
def temp_workspace():
    """Crée un répertoire temporaire pour les entrées et sorties de tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


def test_pdf_converter_generates_markdown(temp_workspace: Path):
    """
    Vérifie qu'un document PDF contenant du texte est converti
    fidèlement en Markdown par le PdfConverter.
    """
    pdf_path = temp_workspace / "test_doc.pdf"
    out_dir = temp_workspace / "out_pdf"

    # Création dynamique d'un PDF avec PyMuPDF
    doc = pymupdf.open()
    page1 = doc.new_page()
    page1.insert_text((50, 72), "Premier Titre de Test", fontsize=18)
    page1.insert_text((50, 110), "Ceci est un paragraphe de test pour le convertisseur PDF.", fontsize=12)

    page2 = doc.new_page()
    page2.insert_text((50, 72), "Deuxième Page de Test", fontsize=16)
    page2.insert_text((50, 110), "Contenu de la seconde page.", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    # Exécution du convertisseur
    converter = PdfConverter(max_workers=2)
    result = converter.convert(file_path=pdf_path, output_dir=out_dir, keep_images=False, ocr=False)

    assert result.pages_count == 2
    assert "Premier Titre de Test" in result.markdown_content
    assert "Deuxième Page de Test" in result.markdown_content


def test_docx_converter_generates_markdown(temp_workspace: Path):
    """
    Vérifie qu'un document Word (.docx) avec titres, paragraphes et tableaux
    est correctement converti en Markdown structuré.
    """
    docx_path = temp_workspace / "test_doc.docx"
    out_dir = temp_workspace / "out_docx"

    # Création d'un document Word structuré avec python-docx
    doc = docx.Document()
    doc.add_heading("Rapport Annuel de Test", level=1)
    doc.add_paragraph("Introduction au document de vérification.")

    # Ajout d'un tableau
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Article"
    table.rows[0].cells[1].text = "Prix"
    table.rows[1].cells[0].text = "Clavier"
    table.rows[1].cells[1].text = "50€"
    doc.save(str(docx_path))

    # Exécution de la conversion
    converter = DocxConverter()
    result = converter.convert(file_path=docx_path, output_dir=out_dir, keep_images=False)

    assert "Rapport Annuel de Test" in result.markdown_content
    assert "Introduction au document" in result.markdown_content
    assert "Clavier" in result.markdown_content


def test_pptx_converter_generates_markdown(temp_workspace: Path):
    """
    Vérifie qu'une présentation PowerPoint (.pptx) produit les sections
    diapositive, puces et notes de présentateur attendues.
    """
    pptx_path = temp_workspace / "test_pres.pptx"
    out_dir = temp_workspace / "out_pptx"

    # Création d'une présentation avec python-pptx
    prs = Presentation()
    slide_layout = prs.slide_layouts[1]  # Titre + Contenu
    slide = prs.slides.add_slide(slide_layout)

    # Titre
    title = slide.shapes.title
    title.text = "Stratégie Globale 2026"

    # Corps de texte avec puces
    body_shape = slide.shapes.placeholders[1]
    tf = body_shape.text_frame
    tf.text = "Objectif numéro 1"
    p2 = tf.add_paragraph()
    p2.text = "Objectif numéro 2"
    p2.level = 1

    # Notes du présentateur
    notes_slide = slide.notes_slide
    notes_text_frame = notes_slide.notes_text_frame
    notes_text_frame.text = "Ne pas oublier de mentionner les indicateurs clés."

    prs.save(str(pptx_path))

    # Exécution de la conversion
    converter = PptxConverter()
    result = converter.convert(file_path=pptx_path, output_dir=out_dir, keep_images=False)

    assert "Diapositive 1" in result.markdown_content
    assert "Stratégie Globale 2026" in result.markdown_content
    assert "Objectif numéro 1" in result.markdown_content
    assert "Notes du présentateur" in result.markdown_content
