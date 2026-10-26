# DocToMarkdown

> Convertisseur haute performance et éco-mémoire de documents **PDF**, **Word (.docx)** et **PowerPoint (.pptx)** vers **Markdown (.md)**, optimisé pour les pipelines LLM, RAG et l'archivage technique.

---

## 📑 Sommaire

1. [Quel Problème Résout DocToMarkdown ?](#-quel-problème-résout-doctomarkdown-)
2. [Le Problème de la Mémoire RAM (3 Go) et la Solution](#-le-problème-de-la-mémoire-ram-3-go-et-la-solution-)
3. [Architecture Zero-Disk Storage](#-architecture-zero-disk-storage-)
4. [Guide d'Utilisation](#-guide-dutilisation-)
5. [Comment Lancer l'Application](#-comment-lancer-lapplication-)
   - [1. En Local (Python)](#1-lancement-en-local-python)
   - [2. Depuis GitHub (Clonage)](#2-lancement-depuis-github)
   - [3. Avec Docker & Docker Compose](#3-lancement-avec-docker--docker-compose)
   - [4. Application de Bureau Native](#4-lancement-en-application-de-bureau-native)
6. [Utilisation via l'API REST](#-utilisation-via-lapi-rest-)
7. [Sécurité et Confidentialité](#-sécurité-et-confidentialité-)

---

## 🎯 Quel Problème Résout DocToMarkdown ?

### 1. La lenteur et les blocages des convertisseurs traditionnels
La majorité des outils de conversion open-source (`pdfminer`, `pypdf`, parseurs pure-Python) s'exécutent sur un seul fil d'exécution (thread) limité par le GIL de Python. Sur un fichier volumineux (> 50 Mo ou contenant des centaines de pages), la conversion prend plusieurs minutes ou échoue par dépassement de mémoire (*Out Of Memory*).
- **DocToMarkdown résout cela** en utilisant le moteur C++ natif de MuPDF combiné à un découpage multi-cœurs adaptatif. Les documents volumineux sont convertis en quelques dizaines de secondes.

### 2. Les formats propriétaires incompatibles avec les LLM (RAG)
Les fichiers `.docx`, `.pptx` et `.pdf` comportent des balises binaires ou XML complexes qui polluent les contextes des modèles d'IA (ChatGPT, Claude, Gemini, Llama).
- **DocToMarkdown résout cela** en extrayant la sémantique pure sous forme de Markdown standard (GitHub Flavored Markdown) : titres hiérarchisés (`#`, `##`), tableaux Markdown propres, listes à puces et blocs de citation, sans code XML inutile.

### 3. La saturation de l'espace disque sur les serveurs
Les convertisseurs classiques sauvegardent les fichiers uploadés et les résultats convertis sur le disque dur sans purge stricte, saturant rapidement les serveurs.
- **DocToMarkdown résout cela** grâce au concept de **Zero-Disk Storage** : les fichiers sources temporaires sont supprimés immédiatement après traitement et les résultats sont servis directement depuis la RAM sans persistance.

---

## 🧠 Le Problème de la Mémoire RAM (3 Go) et la Solution

### Le Diagnostic : Pourquoi un PDF de 46 pages consommait 3 Go de RAM ?
Sur un système moderne doté d'un processeur multi-cœurs (par exemple 24 cœurs logiques), une implémentation naïve de parallélisme sous Windows utilise `multiprocessing.ProcessPoolExecutor(max_workers=os.cpu_count())`.

Sous Windows, le système d'exploitation ne supporte pas le `fork` Unix et utilise obligatoirement le mode **`spawn`** :
1. Chaque worker lance un nouveau processus Python (`python.exe`) complet et indépendant.
2. Chaque processus importe l'intégralité des dépendances du projet (FastAPI, PyMuPDF, python-docx, Pydantic, etc.), ce qui consomme entre **120 Mo et 130 Mo de RAM par worker** avant même de traiter la moindre page.
3. Avec 24 cœurs : 
   $$\text{24 workers} \times 130\text{ Mo} = \mathbf{3{,}12\text{ Go de RAM}}$$
4. Pour un document de seulement 46 pages, le système créait 23 micro-lots de 2 pages répartis sur 24 processus lourds. La machine gaspillait 3 Go de mémoire et perdait un temps considérable à instancier les processus Windows.

### La Solution Implémentée : L'Allocation Adaptative Éco-RAM

DocToMarkdown adapte automatiquement le nombre de processus alloués selon la taille réelle du document :

| Nombre de pages | Processus alloués | Mode d'exécution | Consommation RAM | Temps d'exécution |
| :--- | :---: | :---: | :---: | :---: |
| **$\le$ 80 pages** (ex: 46 pages) | **1 seul worker** | Direct C++ synchrone (**0 processus spawné**) | **$< 35$ Mo** | **$< 3.5$ secondes** |
| **81 à 200 pages** | **2 workers** | Parallèle modéré | **$< 90$ Mo** | **$< 12$ secondes** |
| **$>$ 200 pages** | **3 workers max** | Parallèle haute performance | **$< 140$ Mo** | **$< 25$ secondes** |

#### Mécanismes techniques complémentaires :
- **Libération immédiate des buffers C++** : Appel explicite de `doc.close()` dans un bloc `finally` pour fermer le descripteur MuPDF.
- **Garbage Collection forcé** : Invocations ciblées de `gc.collect()` dès la finalisation du document pour rendre immédiatement la mémoire au système d'exploitation sans attendre le ramasse-miettes différé de Python.

---

## 💾 Architecture Zero-Disk Storage

Pour garantir une sécurité totale et éviter toute saturation de stockage :

1. **Upload en streaming par blocs de 1 Mo** : Le fichier entrant est écrit temporairement sans jamais être chargé entièrement en mémoire vive d'un seul coup.
2. **Purge instantanée du fichier source** : Dès que l'extraction textuelle est terminée, le fichier uploadé est supprimé du disque (`unlink`).
3. **Résultat en mémoire vive (RAM)** : Le texte Markdown converti et les archives `.zip` sont conservés dans un buffer mémoire (`io.BytesIO`) et transmis au client via streaming HTTP direct (`Response(content=...)`).
4. **Tâche de fond de sécurité** : Même en cas de coupure inattendue, une routine d'arrière-plan inspecte et purge tout fichier orphelin toutes les 60 secondes.

---

## 📖 Guide d'Utilisation

### 1. Conversion d'un document
1. Accédez à l'application dans votre navigateur (`http://127.0.0.1:8000`).
2. Déposez vos fichiers (.pdf, .docx, .pptx) dans la zone centrale ou cliquez pour sélectionner un fichier.
3. Choisissez le mode de conversion :
   - **Conversion unitaire** : Cliquez sur le bouton de lecture vert `Convertir ce fichier` sur la ligne du document souhaité.
   - **Conversion par lot** : Cliquez sur le bouton principal `Convertir tous les fichiers`.
4. La fenêtre de chargement s'affiche en temps réel avec le pourcentage d'avancement, le décompte des pages et le chronomètre.
5. Une fois la conversion terminée :
   - Cliquez sur **Aperçu** pour visualiser le rendu HTML ou le code source Markdown brut.
   - Cliquez sur **Télécharger (.md)** pour obtenir le fichier Markdown.

### 2. Comprendre les Options

#### Option : Extraire les images (.zip)
- **Désactivée (par défaut - Recommandé)** : Offre la vitesse de conversion maximale et l'empreinte mémoire la plus faible. Les images binaires intégrées dans le document sont ignorées pour ne conserver que la structure et le contenu textuel.
- **Activée** : Extrait toutes les images du document dans un répertoire `images/` et insère des liens Markdown du type `![image](images/nom.png)`. L'application génère alors une archive `.zip` téléchargeable contenant le Markdown et toutes ses illustrations.

#### Option : OCR automatique (Tesseract)
- **Quand l'activer ?** Uniquement si vous importez des **PDF scannés** (documents numérisés où le texte est une photo plate et ne peut pas être sélectionné à la souris).
- **Comment cela fonctionne ?** Le moteur vérifie d'abord si la page contient du texte numérique. Si la page est vide de tout texte vectoriel, Tesseract OCR analyse l'image matricielle pour en extraire les caractères.

---

## 🚀 Comment Lancer l'Application

### 1. Lancement en Local (Python)

#### Prérequis
- Python 3.11 ou supérieur installé.

#### Procédure
```bash
# 1. Créer un environnement virtuel
python -m venv .venv

# 2. Activer l'environnement virtuel
# Sous Windows (PowerShell) :
.\.venv\Scripts\Activate.ps1
# Sous Linux / macOS :
source .venv/bin/activate

# 3. Installer les dépendances
pip install --upgrade pip
pip install -r requirements.txt

# 4. Lancer le serveur Uvicorn
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Ouvrez votre navigateur sur : **`http://127.0.0.1:8000`**

---

### 2. Lancement depuis GitHub

Pour installer et exécuter le projet depuis un clone GitHub propre :

```bash
# 1. Cloner le dépôt
git clone https://github.com/<organisation-ou-utilisateur>/DocToMarkdown.git
cd DocToMarkdown

# 2. Configurer l'environnement Python
python -m venv .venv

# Sous Windows :
.\.venv\Scripts\Activate.ps1
# Sous Linux :
source .venv/bin/activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Démarrer l'application
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
*Note : Les fichiers du frontend sont déjà précompilés dans `frontend/dist/`. L'application fonctionne immédiatement sans nécessiter Node.js.*

---

### 3. Lancement avec Docker & Docker Compose

Docker permet d'isoler l'application dans un conteneur Linux Debian léger incluant les bibliothèques C++, Pandoc et Tesseract OCR.

#### Méthode A : Avec Docker Compose (Recommandée)

Un fichier `docker-compose.yml` prêt à l'emploi est inclus à la racine du projet.

```bash
# Démarrer le conteneur en arrière-plan
docker compose up -d --build
```
L'application est immédiatement accessible sur **`http://localhost:8000`**.

Pour arrêter le conteneur :
```bash
docker compose down
```

#### Méthode B : Avec Docker CLI classique

```bash
# 1. Construire l'image Docker
docker build -t doctomarkdown:latest .

# 2. Lancer le conteneur avec exposition du port 8000
docker run -d -p 8000:8000 --name doctomarkdown-instance doctomarkdown:latest
```

Pour consulter les logs du conteneur :
```bash
docker logs -f doctomarkdown-instance
```

Pour stopper le conteneur :
```bash
docker stop doctomarkdown-instance
docker rm doctomarkdown-instance
```

#### Variables d'environnement configurables dans Docker :
- `DTM_MAX_WORKERS` : Nombre maximal de workers alloués (défaut : `4`).
- `DTM_MAX_FILE_SIZE_BYTES` : Taille maximale par fichier en octets (défaut : `524288000` = 500 Mo).
- `DTM_STORAGE_TTL_SECONDS` : Durée de conservation maximale des tampons (défaut : `1800` secondes).

---

### 4. Lancement en Application de Bureau Native

DocToMarkdown peut être lancé sous forme d'application de bureau avec une fenêtre autonome sans ouvrir le navigateur classique :

```bash
# Installer pywebview
pip install pywebview

# Lancer la fenêtre d'application
python desktop.py
```

---

## 🔌 Utilisation via l'API REST

DocToMarkdown expose une API REST complète documentée sous Swagger sur `http://127.0.0.1:8000/api/docs`.

### Exemple : Convertir un fichier via cURL

```bash
curl -X POST "http://127.0.0.1:8000/api/convert" \
     -F "files=@mon_document.pdf" \
     -F "keep_images=false" \
     -F "ocr=false"
```
**Réponse JSON :**
```json
{
  "job_ids": ["4ebedab24da849cd8aa7c8a89a10f059"],
  "job_id": "4ebedab24da849cd8aa7c8a89a10f059",
  "count": 1,
  "message": "Conversion initialisée avec succès."
}
```

### Exemple : Télécharger le résultat Markdown

```bash
curl -O -J "http://127.0.0.1:8000/api/jobs/4ebedab24da849cd8aa7c8a89a10f059/download?format=md"
```

### Exemple : Script d'automatisation en Python (`httpx`)

```python
import httpx
import time

URL = "http://127.0.0.1:8000"

with httpx.Client(timeout=60.0) as client:
    # 1. Envoi du document
    with open("rapport.pdf", "rb") as f:
        res = client.post(f"{URL}/api/convert", files={"files": ("rapport.pdf", f, "application/pdf")})
    job_id = res.json()["job_ids"][0]

    # 2. Attente de la fin de conversion
    while True:
        status_res = client.get(f"{URL}/api/jobs/{job_id}").json()
        if status_res["status"] == "done":
            break
        elif status_res["status"] == "error":
            raise RuntimeError(status_res["error"])
        time.sleep(0.5)

    # 3. Récupération du Markdown
    md_res = client.get(f"{URL}/api/jobs/{job_id}/download?format=md")
    with open("rapport.md", "w", encoding="utf-8") as out:
        out.write(md_res.text)
    print("Document converti avec succès en rapport.md")
```

---

## 🛡️ Sécurité et Confidentialité

- **Aucune donnée personnelle** : Le code source ne contient aucun identifiant privé, clé API ou information personnelle.
- **Vérification des signatures binaires (*Magic Bytes*)** : Chaque fichier uploadé est vérifié selon ses premiers octets (`%PDF` pour le PDF, `PK\x03\x04` pour DOCX et PPTX). Un fichier exécutable renommé en `.pdf` est rejeté immédiatement avec un code HTTP 400.
- **Protection anti Zip-Bomb** : Les conteneurs OpenXML (`.docx`, `.pptx`) sont inspectés avant décompression. Tout fichier présentant un ratio de compression anormal (> 100:1) ou un nombre d'entrées supérieur à 10 000 est bloqué pour protéger les ressources du serveur.
- **Sanitisation Path Traversal** : Les noms de fichiers sont assainis pour interdire les séquences relatives (`../`) et caractères non autorisés.
- **Isolation non-root dans Docker** : L'image Docker s'exécute sous un utilisateur dédié non privilégié (`appuser`, UID 1000).

---

## 🧪 Tests Unitaires et Qualité

Pour lancer la suite de tests automatisés :
```bash
pytest -v
```

Pour vérifier le formatage et le typage du code :
```bash
ruff check .
```

---

## 📄 Licence

Ce projet est distribué sous licence libre **MIT**.
