"""
==============================================================================
DocToMarkdown - Lanceur Application de Bureau Native (desktop.py)
==============================================================================

Ce fichier permet d'exécuter DocToMarkdown sous la forme d'une application
de bureau native et autonome avec fenêtre dédiée (via pywebview) :
1. Démarre le serveur web ASGI Uvicorn dans un thread d'arrière-plan daemon.
2. Attend que le serveur réponde sur le port local (127.0.0.1:8000).
3. Ouvre une fenêtre d'application native Windows / macOS / Linux.
4. En cas de fermeture de la fenêtre, le serveur s'arrête proprement.

------------------------------------------------------------------------------
COMMENT PACKAGER CETTE APPLICATION EN .EXE AUTONOME AVEC PYINSTALLER ?
------------------------------------------------------------------------------
Pour créer un exécutable autonome 'DocToMarkdown.exe' distribuable sans Python :

1. Installez PyInstaller :
   pip install pyinstaller

2. Exécutez la commande suivante :
   pyinstaller --noconfirm --onedir --windowed ^
       --add-data "frontend;frontend" ^
       --name "DocToMarkdown" ^
       desktop.py

3. L'exécutable prêt à l'emploi se trouvera dans le dossier 'dist/DocToMarkdown/'.
==============================================================================
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import urllib.request

import uvicorn

from app.config import settings
from app.main import app

logger = logging.getLogger("doctomarkdown.desktop")


def start_uvicorn_server():
    """
    Lance le serveur Uvicorn sur l'interface locale 127.0.0.1.
    """
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=settings.PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server.run()


def wait_for_server_ready(url: str, timeout_seconds: float = 10.0) -> bool:
    """
    Sonde périodiquement l'URL de santé jusqu'à ce que le serveur réponde.
    """
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def main():
    """
    Point d'entrée du lanceur bureau.
    """
    local_url = f"http://127.0.0.1:{settings.PORT}"
    print(f"[*] Démarrage du serveur DocToMarkdown sur {local_url}...")

    # 1. Démarrage du serveur Uvicorn dans un thread d'arrière-plan
    server_thread = threading.Thread(target=start_uvicorn_server, daemon=True)
    server_thread.start()

    # 2. Attente de la disponibilité effective du serveur
    if not wait_for_server_ready(local_url):
        print("[!] Erreur : Le serveur local n'a pas répondu dans le délai imparti.")
        sys.exit(1)

    print("[+] Serveur opérationnel. Ouverture de la fenêtre bureau...")

    # 3. Ouverture de la fenêtre native avec pywebview
    try:
        import webview

        webview.create_window(
            title=f"{settings.APP_NAME} - Convertisseur Haute Performance",
            url=local_url,
            width=1100,
            height=850,
            min_size=(800, 600),
            text_select=True,
        )
        webview.start()
    except Exception as exc:
        # Repli gracieux : ouverture dans le navigateur système par défaut
        print(f"[!] pywebview non disponible ({exc}), ouverture dans le navigateur par défaut...")
        import webbrowser

        webbrowser.open(local_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Arrêt demandé par l'utilisateur.")


if __name__ == "__main__":
    main()
