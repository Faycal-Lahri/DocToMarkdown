"""
==============================================================================
DocToMarkdown - Point d'Entrée Principal FastAPI (app/main.py)
==============================================================================

Ce fichier configure et initialise l'application web FastAPI :
1. Cycle de vie (Lifespan) : Démarrage de la boucle de nettoyage automatique
   en tâche de fond (cleanup.py) et purge propre des fichiers au shutdown.
2. Configuration CORS : Autorise les requêtes multi-origines si nécessaire.
3. Montage de l'API REST : Inclusion du routeur app/routes.py sous /api.
4. Hébergement du Frontend Vanilla : Montage des fichiers statiques (frontend/)
   sur la racine '/' pour une utilisation prête à l'emploi dans le navigateur.
5. Gestion globale des exceptions : Garantit qu'aucune stack trace sensible
   n'est divulguée aux clients en cas d'erreur inattendue.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.cleanup import background_cleanup_loop, purge_all_temporary_files
from app.config import settings
from app.routes import router as api_router

# ==============================================================================
# Configuration du Logging Structuré
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("doctomarkdown")


# ==============================================================================
# Gestionnaire de Cycle de Vie (Lifespan)
# ==============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gère les actions d'initialisation au démarrage et de nettoyage à l'arrêt.
    """
    logger.info("==================================================")
    logger.info("   Démarrage de DocToMarkdown v%s", settings.VERSION)
    logger.info("   Workers alloués : %d cœurs CPU", settings.MAX_WORKERS)
    logger.info("   Taille max autorisée : %d Mo", settings.MAX_FILE_SIZE_BYTES // (1024 * 1024))
    logger.info("==================================================")

    # Initialisation des répertoires de travail
    settings.init_directories()

    # Démarrage de la tâche de nettoyage automatique en arrière-plan
    cleanup_task = asyncio.create_task(
        background_cleanup_loop(
            interval_seconds=settings.CLEANUP_INTERVAL_SECONDS,
            ttl_seconds=settings.STORAGE_TTL_SECONDS,
        )
    )

    yield  # L'application traite les requêtes

    # Arrêt propre : annulation de la boucle de nettoyage et purge
    logger.info("Arrêt de l'application DocToMarkdown...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    purge_all_temporary_files()
    logger.info("Nettoyage d'arrêt terminé avec succès.")


# ==============================================================================
# Instanciation de FastAPI
# ==============================================================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Convertisseur haute performance de documents PDF, DOCX et PPTX vers Markdown.",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Sécurité & CORS : autorise les requêtes pour usage local et conteneurisé
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Middleware de capture globale des exceptions
# ==============================================================================


@app.middleware("http")
async def exception_handling_middleware(request: Request, call_next):
    """
    Capture les exceptions non gérées pour consigner les logs détaillés côté serveur
    tout en renvoyant une réponse JSON propre et sécurisée au client HTTP.
    """
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        logger.exception("Exception non interceptée pour l'URL %s : %s", request.url.path, exc)
        return JSONResponse(status_code=500, content={"detail": "Une erreur interne s'est produite sur le serveur."})


# Montage des routes API
app.include_router(api_router)


# ==============================================================================
# Service du Frontend React (Production Bundle dans frontend/dist)
# ==============================================================================

frontend_base = settings.BASE_DIR / "frontend"
frontend_dist = frontend_base / "dist"
static_serve_dir = frontend_dist if frontend_dist.exists() else frontend_base

if static_serve_dir.exists():
    index_file = static_serve_dir / "index.html"

    @app.get("/", include_in_schema=False)
    async def serve_index():
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"status": "healthy", "message": "Frontend en cours de compilation..."})

    app.mount("/", StaticFiles(directory=str(static_serve_dir), html=True), name="frontend")
else:
    logger.warning("Le répertoire frontend '%s' n'existe pas.", static_serve_dir)
