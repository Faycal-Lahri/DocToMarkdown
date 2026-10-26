import React, { useState, useEffect, useRef } from "react";
import { marked } from "marked";
import {
  FileText,
  Upload,
  Check,
  Copy,
  Download,
  Sun,
  Moon,
  Trash2,
  FileCode,
  Archive,
  ArrowRight,
  Play,
  RotateCw,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  Image as ImageIcon,
  ScanText,
  X,
  StopCircle,
  CheckCircle2,
  AlertCircle,
  Clock,
  Layers,
  FileSpreadsheet
} from "lucide-react";

export default function App() {
  const [theme, setTheme] = useState(() => localStorage.getItem("dtm_theme") || "dark");
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [keepImages, setKeepImages] = useState(false);
  const [ocrEnabled, setOcrEnabled] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDragActive, setIsDragActive] = useState(false);
  const [jobs, setJobs] = useState({});
  const [activePreviewId, setActivePreviewId] = useState(null);
  const [previewContent, setPreviewContent] = useState(null);
  const [viewTab, setViewTab] = useState("rendered"); // 'rendered' | 'raw'
  const [toastText, setToastText] = useState(null);
  const [copied, setCopied] = useState(false);
  const [showInfo, setShowInfo] = useState(false);

  // Pop-up modal de chargement actif
  const [activeModalJobId, setActiveModalJobId] = useState(null);

  const fileInputRef = useRef(null);
  const jobsRef = useRef(jobs);

  // Maintient la référence synchrone pour beforeunload
  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  // Interruption automatique de la conversion si l'utilisateur rafraîchit la page (F5 / Reload / Close)
  useEffect(() => {
    const handleBeforeUnload = () => {
      const runningJobs = Object.values(jobsRef.current).filter((j) => j.status === "running");
      runningJobs.forEach((job) => {
        // Envoi asynchrone garanti via Beacon API lors de la fermeture/refresh
        navigator.sendBeacon(`/api/jobs/${job.job_id}/cancel`);
      });
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, []);

  // Gestion du thème
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("dtm_theme", theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  };

  const notify = (msg) => {
    setToastText(msg);
    setTimeout(() => setToastText(null), 3000);
  };

  // Sélection de fichiers
  const handleFiles = (incoming) => {
    const valid = [".pdf", ".docx", ".pptx"];
    const accepted = Array.from(incoming).filter((f) => {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      return valid.includes(ext);
    });

    if (accepted.length === 0 && incoming.length > 0) {
      notify("Format non supporté. Veuillez sélectionner un PDF, DOCX ou PPTX.");
      return;
    }

    setSelectedFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name + f.size));
      const filtered = accepted.filter((f) => !existing.has(f.name + f.size));
      return [...prev, ...filtered];
    });
  };

  // Interrompre manuellement un job en cours
  const cancelJob = async (jobId) => {
    try {
      await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      setJobs((prev) => ({
        ...prev,
        [jobId]: {
          ...prev[jobId],
          status: "canceled",
          current_step: "Conversion interrompue par l'utilisateur."
        }
      }));
      notify("Conversion interrompue avec succès.");
    } catch (err) {
      console.error("Erreur annulation :", err);
    }
  };

  // Convertir UN SEUL fichier individuel
  const convertSingleFile = async (fileObj) => {
    if (isProcessing) return;
    setIsProcessing(true);

    const formData = new FormData();
    formData.append("files", fileObj);
    formData.append("keep_images", keepImages);
    formData.append("ocr", ocrEnabled);

    try {
      const res = await fetch("/api/convert", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Erreur serveur" }));
        throw new Error(err.detail || `Erreur HTTP ${res.status}`);
      }

      const data = await res.json();
      const jobId = data.job_ids[0];

      setJobs((prev) => ({
        ...prev,
        [jobId]: {
          job_id: jobId,
          filename: fileObj.name,
          status: "running",
          progress: 10,
          current_step: "Initialisation du convertisseur...",
          elapsed_seconds: 0,
          current_page: 0,
          total_pages: 0,
          warnings: [],
          error: null,
          has_images: false,
          has_archive: false
        }
      }));

      // Ouvrir immédiatement le modal de progression
      setActiveModalJobId(jobId);

      // Retirer ce fichier de la sélection en attente
      setSelectedFiles((prev) => prev.filter((f) => !(f.name === fileObj.name && f.size === fileObj.size)));

      bindJobEvents(jobId);
    } catch (err) {
      notify(`Échec : ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  // Convertir TOUS les fichiers sélectionnés d'un coup
  const convertAllFiles = async () => {
    if (selectedFiles.length === 0 || isProcessing) return;
    setIsProcessing(true);

    const formData = new FormData();
    selectedFiles.forEach((f) => formData.append("files", f));
    formData.append("keep_images", keepImages);
    formData.append("ocr", ocrEnabled);

    try {
      const res = await fetch("/api/convert", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Erreur serveur" }));
        throw new Error(err.detail || `Erreur HTTP ${res.status}`);
      }

      const data = await res.json();
      const newEntries = {};

      data.job_ids.forEach((id, index) => {
        const fileObj = selectedFiles[index];
        newEntries[id] = {
          job_id: id,
          filename: fileObj ? fileObj.name : `Document_${index + 1}`,
          status: "running",
          progress: 10,
          current_step: "Démarrage du traitement...",
          elapsed_seconds: 0,
          current_page: 0,
          total_pages: 0,
          warnings: [],
          error: null,
          has_images: false,
          has_archive: false
        };
      });

      setJobs((prev) => ({ ...prev, ...newEntries }));
      setSelectedFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";

      // Ouvrir le modal sur le premier job
      if (data.job_ids.length > 0) {
        setActiveModalJobId(data.job_ids[0]);
      }

      data.job_ids.forEach((id) => bindJobEvents(id));
    } catch (err) {
      notify(`Échec : ${err.message}`);
    } finally {
      setIsProcessing(false);
    }
  };

  // Écoute SSE
  const bindJobEvents = (jobId) => {
    if (window.EventSource) {
      const sse = new EventSource(`/api/jobs/${jobId}/events`);
      sse.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data);
          setJobs((prev) => ({
            ...prev,
            [jobId]: { ...prev[jobId], ...payload }
          }));

          if (payload.status === "done") {
            sse.close();
            setActivePreviewId((cur) => cur || jobId);
          } else if (payload.status === "error" || payload.status === "canceled") {
            sse.close();
          }
        } catch (e) {
          console.error("SSE parse error", e);
        }
      };

      sse.onerror = () => {
        sse.close();
        pollJob(jobId);
      };
    } else {
      pollJob(jobId);
    }
  };

  // Polling de repli
  const pollJob = (jobId) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) return;
        const payload = await res.json();
        setJobs((prev) => ({
          ...prev,
          [jobId]: { ...prev[jobId], ...payload }
        }));

        if (payload.status === "done" || payload.status === "error" || payload.status === "canceled") {
          clearInterval(interval);
          if (payload.status === "done") {
            setActivePreviewId((cur) => cur || jobId);
          }
        }
      } catch (err) {
        console.warn("Poll error", err);
      }
    }, 1200);
  };

  // Chargement de l'aperçu
  useEffect(() => {
    if (!activePreviewId) return;

    const fetchPreview = async () => {
      try {
        const res = await fetch(`/api/jobs/${activePreviewId}/preview`);
        if (!res.ok) return;
        const data = await res.json();
        setPreviewContent(data);
      } catch (err) {
        console.error("Preview error", err);
      }
    };

    fetchPreview();
  }, [activePreviewId, jobs[activePreviewId]?.status]);

  // Copie Markdown
  const copyToClipboard = async () => {
    if (!previewContent?.markdown) return;
    try {
      await navigator.clipboard.writeText(previewContent.markdown);
      setCopied(true);
      notify("Markdown copié dans le presse-papiers.");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      notify("Échec de la copie.");
    }
  };

  const getFormatBadge = (name) => {
    const ext = name.split(".").pop().toLowerCase();
    if (ext === "pdf") return <span className="fmt-pill fmt-pdf">PDF</span>;
    if (ext === "docx") return <span className="fmt-pill fmt-docx">DOCX</span>;
    if (ext === "pptx") return <span className="fmt-pill fmt-pptx">PPTX</span>;
    return <span className="fmt-pill">{ext.toUpperCase()}</span>;
  };

  const formatSize = (bytes) => {
    if (!bytes) return "0 Ko";
    const k = 1024;
    const sizes = ["o", "Ko", "Mo", "Go"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  const activeModalJob = activeModalJobId ? jobs[activeModalJobId] : null;

  return (
    <div className="app-container">
      {/* Barre de navigation supérieure épurée */}
      <header className="navbar">
        <div className="nav-brand">
          <img src="/logo.svg" alt="DocToMarkdown Logo" className="nav-logo" />
          <div className="nav-title-group">
            <span className="nav-name">DocToMarkdown</span>
            <span className="nav-version">v1.0</span>
          </div>
        </div>

        <div className="nav-actions">
          <button
            onClick={toggleTheme}
            className="btn-icon"
            aria-label="Changer de thème"
            title="Thème Clair / Sombre"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
      </header>

      {/* Hero section moderne & concise */}
      <section className="hero">
        <h1 className="hero-title">Convertissez vos documents en Markdown structuré</h1>
        <p className="hero-subtitle">
          Traitement ultra-rapide et éco-mémoire pour vos fichiers <strong>PDF</strong>, <strong>Word (.docx)</strong> et <strong>PowerPoint (.pptx)</strong>.
          Zéro encombrement disque, résultats prêts pour les LLM.
        </p>
      </section>

      {/* Zone de Glisser-Déposer moderne & minimaliste */}
      <div
        className={`drop-area ${isDragActive ? "drag-over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragActive(true);
        }}
        onDragLeave={() => setIsDragActive(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragActive(false);
          if (e.dataTransfer.files) handleFiles(e.dataTransfer.files);
        }}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          type="file"
          ref={fileInputRef}
          multiple
          accept=".pdf,.docx,.pptx"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />

        <div className="drop-icon-circle">
          <Upload size={22} strokeWidth={2} />
        </div>

        <div className="drop-text-main">
          Glissez-déposez vos fichiers ici, ou <span className="text-accent">cliquez pour parcourir</span>
        </div>
        <div className="drop-text-sub">
          Accepte les PDF volumineux (&gt;50 Mo), Word (.docx) et présentations PowerPoint (.pptx)
        </div>
      </div>

      {/* Barre de contrôles et options */}
      <div className="controls-bar">
        <div className="switches-container">
          <label className="switch-row" title="Extrait les images dans un dossier images/ et produit un pack .zip">
            <input
              type="checkbox"
              checked={keepImages}
              onChange={(e) => setKeepImages(e.target.checked)}
            />
            <span className="switch-slider" />
            <span className="switch-text">Extraire les images (.zip)</span>
          </label>

          <label className="switch-row" title="Active Tesseract OCR uniquement sur les pages scannées sans texte sélectionnable">
            <input
              type="checkbox"
              checked={ocrEnabled}
              onChange={(e) => setOcrEnabled(e.target.checked)}
            />
            <span className="switch-slider" />
            <span className="switch-text">OCR automatique (pages scannées)</span>
          </label>
        </div>

        <div className="controls-actions">
          {selectedFiles.length > 1 && (
            <button
              onClick={() => setSelectedFiles([])}
              className="btn-ghost"
              title="Vider la sélection"
            >
              <Trash2 size={13} /> Tout retirer
            </button>
          )}

          <button
            onClick={convertAllFiles}
            disabled={selectedFiles.length === 0 || isProcessing}
            className="btn-primary"
          >
            {isProcessing ? (
              <>
                <RotateCw size={14} className="animate-spin" />
                <span>Conversion en cours...</span>
              </>
            ) : (
              <>
                <span>Convertir {selectedFiles.length > 1 ? `tous les fichiers (${selectedFiles.length})` : "le document"}</span>
                <ArrowRight size={14} />
              </>
            )}
          </button>
        </div>
      </div>

      {/* Accordéon explicatif sobre & discret */}
      <div className="accordion-wrapper">
        <div className="accordion-trigger" onClick={() => setShowInfo(!showInfo)}>
          <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <HelpCircle size={14} /> Aide : Quand activer l'extraction d'images ou l'OCR ?
          </span>
          {showInfo ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </div>

        {showInfo && (
          <div className="accordion-content">
            <div className="help-card">
              <div className="help-title"><ImageIcon size={14} className="text-accent" /> Extraire les images</div>
              <p>
                <strong>Désactivé (par défaut) :</strong> Vitesse maximale et légèreté. Le texte et la mise en page sont extraits en priorité.<br />
                <strong>Activé :</strong> Chaque figure ou photo est enregistrée et liée dans le Markdown sous <code>![image](images/...)</code> au sein d'une archive .zip.
              </p>
            </div>

            <div className="help-card">
              <div className="help-title"><ScanText size={14} className="text-emerald" /> OCR automatique</div>
              <p>
                <strong>Pour les documents normaux :</strong> Laissez désactivé pour convertir en 2 à 4 secondes.<br />
                <strong>Pour les PDF scannés :</strong> Activez cette option si votre fichier est une photocopie où le texte n'est pas sélectionnable à la souris.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Liste des fichiers prêts à être convertis (Conversion unitaire possible) */}
      {selectedFiles.length > 0 && (
        <div className="files-section">
          <div className="section-label">
            Fichiers prêts ({selectedFiles.length}) &bull; Vous pouvez convertir individuellement ou par lot :
          </div>

          <div className="file-cards-list">
            {selectedFiles.map((file, idx) => (
              <div key={idx} className="file-card">
                <div className="file-card-left">
                  {getFormatBadge(file.name)}
                  <span className="file-card-name">{file.name}</span>
                  <span className="file-card-size">{formatSize(file.size)}</span>
                </div>

                <div className="file-card-right">
                  <button
                    onClick={() => convertSingleFile(file)}
                    disabled={isProcessing}
                    className="btn-action-single"
                    title="Convertir uniquement ce fichier"
                  >
                    <Play size={12} fill="currentColor" /> Convertir
                  </button>

                  <button
                    onClick={() => setSelectedFiles((prev) => prev.filter((_, i) => i !== idx))}
                    className="btn-icon-subtle"
                    title="Retirer"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* File de traitement des conversions */}
      {Object.keys(jobs).length > 0 && (
        <section className="queue-section">
          <div className="queue-header">
            <span className="section-label">File des conversions ({Object.keys(jobs).length})</span>
            <button
              onClick={() => {
                setJobs({});
                setActiveModalJobId(null);
              }}
              className="btn-ghost btn-sm"
            >
              Effacer la file
            </button>
          </div>

          <div className="queue-list">
            {Object.values(jobs).map((job) => (
              <div key={job.job_id} className={`queue-item ${job.status}`}>
                <div className="queue-item-top">
                  <div className="queue-item-file">
                    {getFormatBadge(job.filename)}
                    <span className="queue-item-title">{job.filename}</span>
                  </div>

                  <div className="queue-item-state">
                    {job.status === "running" && (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                        <button
                          onClick={() => setActiveModalJobId(job.job_id)}
                          className="btn-view-progress"
                        >
                          Suivi
                        </button>
                        <button
                          onClick={() => cancelJob(job.job_id)}
                          className="btn-stop-subtle"
                          title="Arrêter cette conversion"
                        >
                          <StopCircle size={13} /> Arrêter
                        </button>
                        <span className="status-text running">
                          <RotateCw size={12} className="animate-spin" />
                          <span>{job.elapsed_seconds}s ({Math.round(job.progress)}%)</span>
                        </span>
                      </div>
                    )}

                    {job.status === "done" && (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <span className="status-text done">
                          <Check size={13} strokeWidth={2.5} />
                          <span>Prêt ({job.elapsed_seconds}s)</span>
                        </span>
                        <button
                          onClick={() => setActivePreviewId(job.job_id)}
                          className="btn-secondary btn-sm"
                        >
                          Aperçu
                        </button>
                        <a
                          href={`/api/jobs/${job.job_id}/download?format=md`}
                          className="btn-secondary btn-sm"
                        >
                          <Download size={12} /> .md
                        </a>
                        {(job.has_images || job.has_archive) && (
                          <a
                            href={`/api/jobs/${job.job_id}/download?format=zip`}
                            className="btn-secondary btn-sm"
                          >
                            <Archive size={12} /> .zip
                          </a>
                        )}
                      </div>
                    )}

                    {job.status === "canceled" && (
                      <span className="status-text canceled">
                        <AlertCircle size={13} /> Interrompu
                      </span>
                    )}

                    {job.status === "error" && (
                      <span className="status-text error">
                        <AlertCircle size={13} /> Échec
                      </span>
                    )}
                  </div>
                </div>

                {/* Barre de progression épurée */}
                <div className="clean-progress-track">
                  <div
                    className={`clean-progress-bar ${job.status}`}
                    style={{ width: `${job.progress}%` }}
                  />
                </div>

                <div className="queue-item-meta">
                  <span>{job.current_step}</span>
                  {job.total_pages > 0 && (
                    <span>Page {job.current_page} / {job.total_pages}</span>
                  )}
                </div>

                {job.warnings && job.warnings.length > 0 && (
                  <div className="queue-warnings">
                    {job.warnings.map((w, idx) => (
                      <div key={idx}>⚠️ {w}</div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Visualiseur Markdown Pro */}
      {previewContent && (
        <section className="workbench">
          <div className="workbench-header">
            <div className="workbench-title">
              <FileCode size={16} className="text-accent" />
              <span className="workbench-file-name">{previewContent.filename}.md</span>
              {previewContent.is_truncated && (
                <span className="text-muted text-xs">(Aperçu 200 Ko)</span>
              )}
            </div>

            <div className="workbench-segmented">
              <button
                className={`tab-btn ${viewTab === "rendered" ? "active" : ""}`}
                onClick={() => setViewTab("rendered")}
              >
                Rendu visuel
              </button>
              <button
                className={`tab-btn ${viewTab === "raw" ? "active" : ""}`}
                onClick={() => setViewTab("raw")}
              >
                Code Markdown
              </button>
            </div>

            <div className="workbench-actions">
              <button onClick={copyToClipboard} className="btn-secondary btn-sm">
                {copied ? <Check size={13} className="text-emerald" /> : <Copy size={13} />}
                <span>{copied ? "Copié" : "Copier"}</span>
              </button>

              <a
                href={`/api/jobs/${previewContent.job_id}/download?format=md`}
                className="btn-secondary btn-sm"
              >
                <Download size={13} /> Télécharger (.md)
              </a>

              {previewContent.has_images && (
                <a
                  href={`/api/jobs/${previewContent.job_id}/download?format=zip`}
                  className="btn-primary btn-sm"
                >
                  <Archive size={13} /> Pack (.zip)
                </a>
              )}
            </div>
          </div>

          <div className="workbench-viewer">
            {viewTab === "rendered" ? (
              <div
                className="rendered-markdown"
                dangerouslySetInnerHTML={{ __html: marked.parse(previewContent.markdown || "") }}
              />
            ) : (
              <pre className="raw-markdown">
                <code>{previewContent.markdown}</code>
              </pre>
            )}
          </div>
        </section>
      )}

      {/* ============================================================================== */}
      {/* POP-UP MODAL DE CHARGEMENT ÉPURÉ & PROFESSIONNEL (AVEC BOUTON ARRÊT / REFRESH) */}
      {/* ============================================================================== */}
      {activeModalJob && (
        <div className="clean-modal-backdrop" onClick={(e) => {
          if (e.target === e.currentTarget) setActiveModalJobId(null);
        }}>
          <div className="clean-modal-dialog">
            {/* Header du modal */}
            <div className="clean-modal-header">
              <div className="clean-modal-file">
                {getFormatBadge(activeModalJob.filename)}
                <span className="clean-modal-title">{activeModalJob.filename}</span>
              </div>
              <button
                onClick={() => setActiveModalJobId(null)}
                className="clean-modal-close"
                title="Fermer ou réduire le dialogue"
              >
                <X size={16} />
              </button>
            </div>

            {/* Corps du modal : En cours */}
            {activeModalJob.status === "running" && (
              <div className="clean-modal-body">
                {/* Jauge de progression circulaire moderne */}
                <div className="progress-ring-box">
                  <svg className="progress-ring-svg" width="100" height="100">
                    <circle
                      className="progress-ring-bg"
                      stroke="currentColor"
                      strokeWidth="6"
                      fill="transparent"
                      r="42"
                      cx="50"
                      cy="50"
                    />
                    <circle
                      className="progress-ring-indicator"
                      stroke="currentColor"
                      strokeWidth="6"
                      strokeDasharray={264}
                      strokeDashoffset={264 - (264 * Math.max(5, activeModalJob.progress)) / 100}
                      strokeLinecap="round"
                      fill="transparent"
                      r="42"
                      cx="50"
                      cy="50"
                    />
                  </svg>
                  <div className="progress-ring-text">
                    <span className="progress-ring-percent">{Math.round(activeModalJob.progress)}%</span>
                  </div>
                </div>

                {/* Métriques claires */}
                <div className="clean-modal-info">
                  <h4 className="clean-modal-status-text">{activeModalJob.current_step}</h4>
                  <div className="clean-modal-details">
                    {activeModalJob.total_pages > 0 && (
                      <span>Page {activeModalJob.current_page} sur {activeModalJob.total_pages}</span>
                    )}
                    <span>&bull;</span>
                    <span>Temps : {activeModalJob.elapsed_seconds}s</span>
                  </div>
                </div>

                {/* Bouton d'arrêt d'exécution explicite */}
                <div className="clean-modal-footer">
                  <button
                    onClick={() => cancelJob(activeModalJob.job_id)}
                    className="btn-danger-outline"
                  >
                    <StopCircle size={15} /> Arrêter la conversion
                  </button>
                  <button
                    onClick={() => setActiveModalJobId(null)}
                    className="btn-ghost btn-sm"
                  >
                    Réduire en tâche de fond
                  </button>
                </div>
              </div>
            )}

            {/* Corps du modal : Terminé avec succès */}
            {activeModalJob.status === "done" && (
              <div className="clean-modal-body success-state">
                <div className="success-badge-circle">
                  <CheckCircle2 size={36} className="text-emerald" />
                </div>
                <h3>Conversion terminée !</h3>
                <p className="text-muted text-sm">
                  Document transformé avec succès en <strong>{activeModalJob.elapsed_seconds} seconde(s)</strong>.
                </p>

                <div className="modal-cta-row">
                  <button
                    onClick={() => {
                      setActivePreviewId(activeModalJob.job_id);
                      setActiveModalJobId(null);
                    }}
                    className="btn-primary"
                  >
                    <FileText size={14} /> Voir l'aperçu
                  </button>

                  <a
                    href={`/api/jobs/${activeModalJob.job_id}/download?format=md`}
                    className="btn-secondary"
                  >
                    <Download size={14} /> Télécharger .md
                  </a>

                  {(activeModalJob.has_images || activeModalJob.has_archive) && (
                    <a
                      href={`/api/jobs/${activeModalJob.job_id}/download?format=zip`}
                      className="btn-secondary"
                    >
                      <Archive size={14} /> Pack .zip
                    </a>
                  )}
                </div>
              </div>
            )}

            {/* Corps du modal : Interrompu */}
            {activeModalJob.status === "canceled" && (
              <div className="clean-modal-body canceled-state">
                <div className="canceled-badge-circle">
                  <StopCircle size={36} className="text-muted" />
                </div>
                <h3>Conversion interrompue</h3>
                <p className="text-muted text-sm">
                  Le traitement a été arrêté. Les fichiers temporaires ont été immédiatement purgés du système.
                </p>
                <button
                  onClick={() => setActiveModalJobId(null)}
                  className="btn-secondary btn-sm"
                  style={{ marginTop: "1rem" }}
                >
                  Fermer
                </button>
              </div>
            )}

            {/* Corps du modal : Échec */}
            {activeModalJob.status === "error" && (
              <div className="clean-modal-body error-state">
                <div className="error-badge-circle">
                  <AlertCircle size={36} className="text-danger" />
                </div>
                <h3>Échec de la conversion</h3>
                <p className="text-muted text-sm">
                  {activeModalJob.error || "Une erreur inattendue est survenue."}
                </p>
                <button
                  onClick={() => setActiveModalJobId(null)}
                  className="btn-secondary btn-sm"
                  style={{ marginTop: "1rem" }}
                >
                  Fermer
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Toast minimal */}
      {toastText && (
        <div className="clean-toast">
          <span>{toastText}</span>
        </div>
      )}
    </div>
  );
}
