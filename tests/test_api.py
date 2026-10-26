"""
==============================================================================
DocToMarkdown - Tests d'Intégration API REST (tests/test_api.py)
==============================================================================

Ces tests valident les endpoints de l'application via le TestClient de FastAPI :
1. GET /api/health : Vérification de l'état système.
2. POST /api/convert : Téléversement multipart et initialisation de job.
3. GET /api/jobs/{id} : Suivi de la conversion.
4. GET /api/jobs/{id}/preview : Récupération de l'aperçu Markdown.
5. GET /api/jobs/{id}/download : Téléchargement du document.
6. Gestion des cas d'erreur HTTP (400, 404, etc.).
"""

from __future__ import annotations

import io
import time

import pymupdf
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_health_check():
    """
    Vérifie que l'endpoint de santé répond un statut HTTP 200 et les métadonnées.
    """
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "DocToMarkdown" in data["app_name"]
    assert "version" in data


def test_api_convert_and_retrieve_flow():
    """
    Vérifie le cycle complet d'un document via l'API :
    Upload -> Création de Job -> Attente du statut DONE -> Aperçu -> Téléchargement.
    """
    # 1. Génération d'un PDF valide en mémoire
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Titre API Integration Test", fontsize=16)
    page.insert_text((50, 110), "Paragraphe de test transmis par multipart.", fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()

    # 2. Requête d'upload vers /api/convert
    files = [("files", ("integration_test.pdf", io.BytesIO(pdf_bytes), "application/pdf"))]
    upload_res = client.post("/api/convert", files=files, data={"keep_images": "false", "ocr": "false"})
    assert upload_res.status_code == 202
    res_data = upload_res.json()
    assert "job_ids" in res_data
    assert len(res_data["job_ids"]) == 1

    job_id = res_data["job_ids"][0]

    # 3. Attente active de la fin du traitement en arrière-plan
    max_wait = 15  # 15 secondes max
    start = time.time()
    final_status = None

    while time.time() - start < max_wait:
        poll_res = client.get(f"/api/jobs/{job_id}")
        assert poll_res.status_code == 200
        job_data = poll_res.json()
        final_status = job_data["status"]
        if final_status in ("done", "error"):
            break
        time.sleep(0.3)

    assert final_status == "done"

    # 4. Vérification de l'aperçu
    preview_res = client.get(f"/api/jobs/{job_id}/preview")
    assert preview_res.status_code == 200
    preview_data = preview_res.json()
    assert "Titre API Integration Test" in preview_data["markdown"]

    # 5. Vérification du téléchargement du fichier .md
    download_res = client.get(f"/api/jobs/{job_id}/download?format=md")
    assert download_res.status_code == 200
    assert "Titre API Integration Test" in download_res.text

    # 6. Suppression du job
    del_res = client.delete(f"/api/jobs/{job_id}")
    assert del_res.status_code == 200


def test_api_invalid_job_returns_404():
    """
    Vérifie qu'un identifiant de job inexistant renvoie une erreur 404 Not Found.
    """
    response = client.get("/api/jobs/non_existent_job_12345")
    assert response.status_code == 404
