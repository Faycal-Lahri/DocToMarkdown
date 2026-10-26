"""
==============================================================================
DocToMarkdown - Script de Benchmark de Performance (benchmark.py)
==============================================================================

Ce script mesure les performances réelles du moteur de conversion PDF :
1. Génère un document PDF authentique contenant du texte et dépassant les 50 Mo.
2. Exécute la conversion multi-cœurs via le PdfConverter.
3. Mesure le temps de traitement avec haute précision (time.perf_counter).
4. Valide l'objectif de performance :
   - Objectif idéal : < 20 secondes.
   - Limite maximale acceptable : < 60 secondes.
5. Nettoie les fichiers de test après exécution.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

import pymupdf

from app.config import settings
from app.converters.pdf_converter import PdfConverter

# Texte de remplissage pour simuler des rapports d'entreprise denses
LOREM_TEXT = (
    """
DocToMarkdown - Rapport de Performance et Analyse Système.
Dans les architectures logicielles modernes, l'ingestion et la transformation de flux documentaires
hétérogènes imposent des contraintes strictes sur la consommation de mémoire vive et la latence
de traitement. Les moteurs traditionnels sérialisent les documents en mémoire, ce qui sature
les ressources en cas de forte concurrence.
Le découpage par lots combiné à l'utilisation des processus parallèles permet de saturer l'ensemble
des cœurs de calcul du microprocesseur hôte sans subir la contention du verrou global (GIL).
Chaque travailleur réplique l'environnement d'accès aux flux binaires MuPDF et génère
un sous-ensemble cohérent du texte balisé au format Markdown GFM (GitHub Flavored Markdown).
"""
    * 4
)


def generate_benchmark_pdf(target_path: Path, min_size_bytes: int = 51 * 1024 * 1024) -> int:
    """
    Génère un document PDF volumineux avec du texte réel jusqu'à dépasser la taille cible.

    Paramètres:
        target_path: Chemin où enregistrer le fichier PDF.
        min_size_bytes: Taille minimale en octets (51 Mo par défaut).

    Retourne:
        Le nombre total de pages générées.
    """
    print(f"[*] Génération d'un PDF de test de plus de {min_size_bytes // (1024 * 1024)} Mo...")
    doc = pymupdf.open()
    page_count = 0
    # On génère environ 85 pages contenant du texte réel et un flux d'image unique par page
    # pour atteindre > 50 Mo en 2 secondes sans déduplication interne
    while True:
        page = doc.new_page(width=595, height=842)  # Format A4 standard
        page_count += 1

        # Insertion de texte dense et varié
        page.insert_text((50, 60), f"Section {page_count} : Analyse Technique Avancée & Performance", fontsize=15)
        rect = pymupdf.Rect(50, 80, 545, 450)
        page.insert_textbox(rect, f"Page {page_count}\n" + LOREM_TEXT, fontsize=10)

        # Insertion d'un flux d'image non compressible de ~600 Ko par page
        raw_samples = os.urandom(500 * 350 * 3)
        pix = pymupdf.Pixmap(pymupdf.csRGB, 500, 350, raw_samples, False)
        page.insert_image(pymupdf.Rect(50, 470, 500, 780), pixmap=pix)

        if page_count % 10 == 0:
            doc.save(str(target_path), deflate=False)
            current_size = target_path.stat().st_size
            print(f"    -> {page_count} pages générées | Taille : {current_size / (1024 * 1024):.1f} Mo")
            if current_size >= min_size_bytes:
                break

    doc.close()
    final_size = target_path.stat().st_size
    print(f"[+] PDF généré avec succès : {page_count} pages, {final_size / (1024 * 1024):.2f} Mo.")
    return page_count


def run_benchmark():
    """
    Point d'entrée du banc d'essai de performance.
    """
    print("\n=======================================================")
    print("      DocToMarkdown - Banc d'Essai de Performance      ")
    print("=======================================================")
    print(f"Cœurs CPU détectés / alloués : {settings.MAX_WORKERS}")
    print(f"Plateforme : {sys.platform} | Python : {sys.version.split()[0]}")
    print("-------------------------------------------------------\n")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        pdf_file = temp_path / "benchmark_50mb.pdf"
        output_dir = temp_path / "benchmark_output"

        # 1. Génération du document de test
        gen_start = time.perf_counter()
        total_pages = generate_benchmark_pdf(pdf_file, min_size_bytes=51 * 1024 * 1024)
        gen_duration = time.perf_counter() - gen_start
        print(f"Temps de génération du PDF : {gen_duration:.2f} s\n")

        file_size_mb = pdf_file.stat().st_size / (1024 * 1024)

        # 2. Exécution du convertisseur avec chronométrage
        print("[*] Lancement de la conversion haute performance en cours...")
        converter = PdfConverter(max_workers=settings.MAX_WORKERS)

        def progress_tracker(pct: float, cur_p: int, tot_p: int, msg: str):
            # Affichage de progression sur une seule ligne
            print(
                f"\r    Progression : {pct:5.1f}% | Pages : {cur_p:3d}/{tot_p:3d} | {msg[:40]:<40}", end="", flush=True
            )

        conv_start = time.perf_counter()
        result = converter.convert(
            file_path=pdf_file,
            output_dir=output_dir,
            keep_images=False,  # Option par défaut recommandée pour la performance
            ocr=False,
            progress_callback=progress_tracker,
        )
        conv_duration = time.perf_counter() - conv_start
        print()  # Nouvelle ligne après la progression

        pages_per_second = total_pages / conv_duration if conv_duration > 0 else 0

        # 3. Affichage des Résultats
        print("\n=======================================================")
        print("                  RÉSULTATS OBTENUS                    ")
        print("=======================================================")
        print(f"Taille du fichier test  : {file_size_mb:.2f} Mo")
        print(f"Nombre total de pages   : {total_pages} pages")
        print(f"Workers parallèles      : {settings.MAX_WORKERS} processus")
        print(f"Temps de conversion     : {conv_duration:.2f} secondes")
        print(f"Vitesse de traitement   : {pages_per_second:.1f} pages / seconde")
        print(f"Caractères Markdown     : {len(result.markdown_content):,} caractères")
        print("-------------------------------------------------------")

        # 4. Évaluation du critère contractuel
        if conv_duration < 20.0:
            print(">>> RÉSULTAT : EXCELLENT ! (Objectif optimal < 20s ATTEINT) <<<")
            success = True
        elif conv_duration <= 60.0:
            print(">>> RÉSULTAT : VALIDE ! (Inférieur à la limite max de 60s) <<<")
            success = True
        else:
            print(f">>> RÉSULTAT : ÉCHEC ! ({conv_duration:.2f}s > 60s) <<<")
            success = False

        print("=======================================================\n")
        assert success, f"Le benchmark a dépassé le délai maximal autorisé : {conv_duration:.2f}s > 60s"
        return conv_duration, file_size_mb, total_pages


if __name__ == "__main__":
    run_benchmark()
