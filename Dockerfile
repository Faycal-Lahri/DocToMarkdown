# ==============================================================================
# DocToMarkdown - Image Docker Haute Performance
# ==============================================================================

FROM python:3.12-slim

# Empêche Python d'écrire des fichiers .pyc sur disque et active le mode unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Installation des dépendances système (Tesseract OCR avec langues français/anglais, pandoc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-eng \
    pandoc \
    libmupdf-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copie et installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copie du code source et des fichiers statiques
COPY app/ app/
COPY frontend/ frontend/

# Création des dossiers de stockage temporaire
RUN mkdir -p storage/uploads storage/outputs

# Exposition du port HTTP
EXPOSE 8000

# Utilisateur non-root pour des raisons de sécurité
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Commande de démarrage avec Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
