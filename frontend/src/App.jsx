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
  Sparkles,
  Cpu,
  Layers,
  Minimize2,
  X,
  ExternalLink,
  Zap,
  Activity,
  CheckCircle2,
  AlertTriangle
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

  // Modal de chargement / Scanner interactif
  const [activeModalJobId, setActiveModalJobId] = useState(null);

  const fileInputRef = useRef(null);

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
    setTimeout(() => setToastText(null), 3200);
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
          current_step: "Initialisation du moteur C++ MuPDF...",
          elapsed_seconds: 0,
          current_page: 0,
          total_pages: 0,
          warnings: [],
          error: null,
          has_images: false,
          has_archive: false
        }
      }));

      // Ouverture immédiate du Pop-up de chargement senior UX
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
          current_step: "Initialisation du traitement...",
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

      // Ouvrir le Pop-up sur le premier job
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
          } else if (payload.status === "error") {
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

        if (payload.status === "done" || payload.status === "error") {
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

  const getFormatClass = (name) => {
    const ext = name.split(".").pop().toLowerCase();
    if (ext === "pdf") return "format-badge pdf";
    if (ext === "docx") return "format-badge docx";
    if (ext === "pptx") return "format-badge pptx";
    return "format-badge";
  };

  const formatSize = (bytes) => {
    if (!bytes) return "0 Ko";
    const k = 1024;
    const sizes = ["o", "Ko", "Mo", "Go"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  // Job actuellement affiché dans le Pop-up Modal
  const activeModalJob = activeModalJobId ? jobs[activeModalJobId] : null;

  return (
    <div className="workspace">
      {/* Topbar avec Logo officiel */}
      <header className="topbar">
        <div className="brand-section">
          <img src="/logo.svg" alt="DocToMarkdown Logo" className="brand-logo-img" />
          <div className="brand-title-wrap">
            <span className="brand-name">DocToMarkdown</span>
            <span className="brand-tag">v1.0 Pro</span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          {/* Badge Mémoire & Architecture */}
          <div className="eco-memory-badge" title="Moteur optimisé : moins de 45 Mo de RAM">
            <Cpu size={13} className="eco-icon" />
            <span>Moteur Éco-RAM &bull; Multi-cœurs</span>
          </div>

          <button
            onClick={toggleTheme}
            className="theme-toggle-btn"
            aria-label="Changer de thème"
            title="Thème Clair / Sombre"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
      </header>

      {/* Titre & Description de l'outil */}
      <div className="page-intro">
        <h1 className="page-title">Convertisseur Haute Performance vers Markdown</h1>
        <p className="page-description">
          Convertissez vos PDF volumineux (&gt;50 Mo), documents Word (.docx) et présentations PowerPoint (.pptx)
          en Markdown structuré ultra-propre avec un découpage parallèle instantané et une empreinte mémoire minimale.
        </p>
      </div>

      {/* Zone de Glisser-Déposer avec animations réactives */}
      <div
        className={`drop-zone ${isDragActive ? "active" : ""}`}
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

        {/* Effet Scanner Laser d'attente */}
        <div className="drop-beam" />

        <div className="drop-icon-box">
          <Upload size={22} strokeWidth={2.2} />
        </div>

        <div className="drop-title">
          Glissez-déposez vos fichiers ici, ou <span className="browse-link">parcourez votre ordinateur</span>
        </div>
        <div className="drop-hint">
          PDF volumineux (&gt;50 Mo) &bull; Word (.docx) &bull; PowerPoint (.pptx)
        </div>
      </div>

      {/* Barre d'options & Déclenchement */}
      <div className="settings-strip">
        <div className="toggle-group">
          <div
            className={`toggle-item ${keepImages ? "checked" : ""}`}
            onClick={() => setKeepImages(!keepImages)}
            title="Extrait les images dans un sous-dossier et crée un pack .zip complet"
          >
            <div className="switch-control" />
            <span className="toggle-label">Extraire les images (.zip)</span>
          </div>

          <div
            className={`toggle-item ${ocrEnabled ? "checked" : ""}`}
            onClick={() => setOcrEnabled(!ocrEnabled)}
            title="Active la reconnaissance optique Tesseract sur les pages scannées"
          >
            <div className="switch-control" />
            <span className="toggle-label">OCR automatique (pages scannées)</span>
          </div>
        </div>

        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
          {selectedFiles.length > 1 && (
            <button
              onClick={() => setSelectedFiles([])}
              className="btn-subtle"
            >
              <Trash2 size={13} /> Tout retirer
            </button>
          )}

          <button
            onClick={convertAllFiles}
            disabled={selectedFiles.length === 0 || isProcessing}
            className="btn-primary-action"
          >
            {isProcessing ? (
              <>
                <RotateCw size={14} className="animate-spin" />
                <span>Conversion...</span>
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

      {/* Accordéon explicatif interactif */}
      <div className="info-accordion">
        <div className="info-accordion-header" onClick={() => setShowInfo(!showInfo)}>
          <span style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <HelpCircle size={15} /> Comprendre les options : Extraire les images &amp; OCR automatique
          </span>
          {showInfo ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>

        {showInfo && (
          <div className="info-accordion-body">
            <div className="info-box">
              <h4><ImageIcon size={15} color="var(--accent-blue)" /> Extraire les images</h4>
              <p>
                <strong>Désactivé (par défaut) :</strong> Vitesse maximale et consommation mémoire ultra-faible. Les images binaires sont ignorées pour convertir un gros fichier en quelques secondes.<br />
                <strong>Activé :</strong> Chaque image du document est isolée et référencée dans le Markdown. Vous téléchargez un pack <strong>.zip</strong> complet contenant le Markdown et son dossier d'images.
              </p>
            </div>

            <div className="info-box">
              <h4><ScanText size={15} color="var(--accent-emerald)" /> OCR automatique (Tesseract)</h4>
              <p>
                <strong>Quand l'activer ?</strong> Sur des <strong>PDF scannés</strong> (photos de documents papier où le texte n'est pas sélectionnable à la souris).<br />
                <strong>Comment ça marche ?</strong> Tesseract analyse visuellement les formes des lettres pour les transcrire en texte. C'est plus lent (1 à 2s par page scannée), mais indispensable si la page est une image plate.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Liste des fichiers sélectionnés : Conversion Un par Un possible */}
      {selectedFiles.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Fichiers prêts ({selectedFiles.length}) &bull; Vous pouvez les convertir individuellement ou tous ensemble :
          </div>

          <div className="staged-files-list">
            {selectedFiles.map((file, idx) => (
              <div key={idx} className="staged-row">
                <div style={{ display: "flex", alignItems: "center", gap: "0.65rem" }}>
                  <span className={getFormatClass(file.name)}>
                    {file.name.split(".").pop().toUpperCase()}
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontWeight: 500 }}>{file.name}</span>
                  <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
                    ({formatSize(file.size)})
                  </span>
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                  {/* Bouton de conversion individuelle */}
                  <button
                    onClick={() => convertSingleFile(file)}
                    disabled={isProcessing}
                    className="btn-convert-single"
                    title="Convertir uniquement ce fichier"
                  >
                    <Play size={12} fill="currentColor" /> Convertir ce fichier
                  </button>

                  {/* Bouton de suppression individuelle */}
                  <button
                    onClick={() => setSelectedFiles((prev) => prev.filter((_, i) => i !== idx))}
                    className="btn-subtle"
                    style={{ padding: "0.35rem 0.5rem" }}
                    title="Retirer ce fichier"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* File de traitement avec animation de scanner */}
      {Object.keys(jobs).length > 0 && (
        <section style={{ display: "flex", flexDirection: "column", gap: "0.85rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
              File de conversion ({Object.keys(jobs).length})
            </span>
            <button
              onClick={() => {
                setJobs({});
                setActiveModalJobId(null);
              }}
              className="btn-subtle"
              style={{ fontSize: "0.75rem", padding: "0.25rem 0.55rem" }}
            >
              Effacer la file
            </button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.65rem" }}>
            {Object.values(jobs).map((job) => (
              <div
                key={job.job_id}
                className={`queue-row-card ${job.status === "running" ? "running" : ""}`}
              >
                <div className="row-top">
                  <div className="file-info-group">
                    <span className={getFormatClass(job.filename)}>
                      {job.filename.split(".").pop().toUpperCase()}
                    </span>
                    <span className="file-name-text">{job.filename}</span>
                  </div>

                  <div className="status-badge-inline">
                    {job.status === "running" && (
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <button
                          onClick={() => setActiveModalJobId(job.job_id)}
                          className="btn-open-scanner"
                          title="Ouvrir la vue détaillée de conversion"
                        >
                          <Activity size={13} className="animate-pulse" /> Scanner en direct
                        </button>
                        <span className="status-badge-inline running">
                          <RotateCw size={13} className="animate-spin" />
                          <span>{job.elapsed_seconds}s &bull; {Math.round(job.progress)}%</span>
                        </span>
                      </div>
                    )}

                    {job.status === "done" && (
                      <span className="status-badge-inline done">
                        <Check size={14} strokeWidth={2.5} />
                        <span>Terminé en {job.elapsed_seconds}s</span>
                      </span>
                    )}

                    {job.status === "error" && (
                      <span className="status-badge-inline error">
                        Échec
                      </span>
                    )}

                    {job.status === "done" && (
                      <div style={{ display: "flex", gap: "0.4rem", marginLeft: "0.5rem" }}>
                        <button
                          onClick={() => setActivePreviewId(job.job_id)}
                          className="btn-subtle"
                          style={{ borderColor: "var(--border-focus)", color: "var(--text-primary)" }}
                        >
                          Aperçu
                        </button>
                        <a
                          href={`/api/jobs/${job.job_id}/download?format=md`}
                          className="btn-subtle"
                        >
                          <Download size={13} /> .md
                        </a>
                        {(job.has_images || job.has_archive) && (
                          <a
                            href={`/api/jobs/${job.job_id}/download?format=zip`}
                            className="btn-subtle"
                          >
                            <Archive size={13} /> .zip
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Barre de progression fluide */}
                <div className="progress-rail">
                  <div
                    className={`progress-indicator ${job.status}`}
                    style={{ width: `${job.progress}%` }}
                  />
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "var(--text-muted)" }}>
                  <span>{job.current_step}</span>
                  {job.total_pages > 0 && (
                    <span>Page {job.current_page} / {job.total_pages}</span>
                  )}
                </div>

                {job.warnings && job.warnings.length > 0 && (
                  <div style={{ fontSize: "0.78rem", color: "var(--accent-amber)" }}>
                    {job.warnings.map((w, idx) => (
                      <div key={idx}>⚠️ {w}</div>
                    ))}
                  </div>
                )}

                {job.status === "error" && (
                  <div style={{ fontSize: "0.8rem", color: "var(--accent-rose)" }}>
                    ❌ {job.error || "Une erreur inattendue est survenue."}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Visualiseur Markdown Pro */}
      {previewContent && (
        <section className="markdown-workbench">
          <div className="workbench-toolbar">
            <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
              <FileCode size={16} color="var(--accent-blue)" />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.85rem", fontWeight: 600 }}>
                {previewContent.filename}.md
              </span>
              {previewContent.is_truncated && (
                <span style={{ fontSize: "0.75rem", color: "var(--accent-amber)" }}>
                  (Aperçu partiel 200 Ko)
                </span>
              )}
            </div>

            {/* Sélecteur d'onglets épuré */}
            <div className="segmented-control">
              <button
                className={`segment-btn ${viewTab === "rendered" ? "active" : ""}`}
                onClick={() => setViewTab("rendered")}
              >
                Rendu HTML
              </button>
              <button
                className={`segment-btn ${viewTab === "raw" ? "active" : ""}`}
                onClick={() => setViewTab("raw")}
              >
                Markdown Brut
              </button>
            </div>

            {/* Actions de téléchargement et copie */}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={copyToClipboard} className="btn-subtle">
                {copied ? <Check size={14} color="var(--accent-emerald)" /> : <Copy size={14} />}
                <span>{copied ? "Copié" : "Copier"}</span>
              </button>

              <a
                href={`/api/jobs/${previewContent.job_id}/download?format=md`}
                className="btn-subtle"
              >
                <Download size={14} /> Télécharger .md
              </a>

              {previewContent.has_images && (
                <a
                  href={`/api/jobs/${previewContent.job_id}/download?format=zip`}
                  className="btn-primary-action"
                  style={{ textDecoration: "none", padding: "0.45rem 0.85rem" }}
                >
                  <Archive size={14} /> Pack .zip
                </a>
              )}
            </div>
          </div>

          <div className="workbench-content">
            {viewTab === "rendered" ? (
              <div
                className="md-output"
                dangerouslySetInnerHTML={{ __html: marked.parse(previewContent.markdown || "") }}
              />
            ) : (
              <pre className="md-raw-code">
                <code>{previewContent.markdown}</code>
              </pre>
            )}
          </div>
        </section>
      )}

      {/* ============================================================================== */}
      {/* POP-UP DE CHARGEMENT SENIOR UX/UI (MODAL INTERACTIF AVEC SCANNER HOLOGRAPHIQUE) */}
      {/* ============================================================================== */}
      {activeModalJob && (
        <div className="modal-backdrop" onClick={(e) => {
          if (e.target === e.currentTarget) setActiveModalJobId(null);
        }}>
          <div className="modal-scanner-card" onClick={(e) => e.stopPropagation()}>
            {/* Header du modal */}
            <div className="modal-header">
              <div className="modal-file-info">
                <span className={getFormatClass(activeModalJob.filename)}>
                  {activeModalJob.filename.split(".").pop().toUpperCase()}
                </span>
                <div>
                  <h3 className="modal-file-title">{activeModalJob.filename}</h3>
                  <div className="modal-telemetry-row">
                    <span className="telemetry-pill eco">
                      <Zap size={11} /> RAM Éco : &lt; 45 Mo
                    </span>
                    <span className="telemetry-pill">
                      <Cpu size={11} /> Moteur C++ MuPDF
                    </span>
                    <span className="telemetry-pill">
                      <Layers size={11} /> Stream Direct RAM
                    </span>
                  </div>
                </div>
              </div>

              <button
                className="modal-close-btn"
                onClick={() => setActiveModalJobId(null)}
                title="Minimiser / Traiter en arrière-plan"
              >
                <Minimize2 size={16} />
              </button>
            </div>

            {/* Corps du modal : État en cours vs État terminé */}
            {activeModalJob.status === "running" && (
              <div className="modal-body-scanning">
                {/* Visualiseur Holographique de Document & Faisceau Laser */}
                <div className="holo-doc-container">
                  <div className="holo-doc-sheet">
                    <div className="holo-line header" />
                    <div className="holo-line p1" />
                    <div className="holo-line p2" />
                    <div className="holo-line p3" />
                    <div className="holo-line p4" />
                    <div className="holo-table">
                      <div className="holo-cell" />
                      <div className="holo-cell" />
                      <div className="holo-cell" />
                    </div>
                  </div>

                  {/* Faisceau laser scanner traversant */}
                  <div className="holo-scanner-laser" />

                  {/* Vagues radar circulaires en arrière-plan */}
                  <div className="holo-radar-ring ring-1" />
                  <div className="holo-radar-ring ring-2" />
                </div>

                {/* Métriques d'avancement dynamiques */}
                <div className="modal-metrics-grid">
                  <div className="metric-box">
                    <span className="metric-label">Progression</span>
                    <span className="metric-value highlight">{Math.round(activeModalJob.progress)}%</span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-label">Pages traitées</span>
                    <span className="metric-value">
                      {activeModalJob.total_pages > 0
                        ? `${activeModalJob.current_page} / ${activeModalJob.total_pages}`
                        : "Comptage..."}
                    </span>
                  </div>
                  <div className="metric-box">
                    <span className="metric-label">Temps écoulé</span>
                    <span className="metric-value">{activeModalJob.elapsed_seconds}s</span>
                  </div>
                </div>

                {/* Grand indicateur de progression à lueur néon */}
                <div className="modal-neon-rail">
                  <div
                    className="modal-neon-fill"
                    style={{ width: `${activeModalJob.progress}%` }}
                  />
                </div>

                {/* Étape textuelle active */}
                <div className="modal-step-status">
                  <RotateCw size={14} className="animate-spin" color="var(--accent-blue)" />
                  <span>{activeModalJob.current_step}</span>
                </div>

                <div className="modal-hint-footer">
                  Vous pouvez réduire cette fenêtre à tout moment, la conversion continue sans interruption.
                </div>
              </div>
            )}

            {/* État Terminé avec succès */}
            {activeModalJob.status === "done" && (
              <div className="modal-body-success">
                <div className="success-halo-icon">
                  <CheckCircle2 size={48} color="var(--accent-emerald)" />
                </div>

                <h4 className="success-headline">Conversion réussie avec succès !</h4>
                <p className="success-subtext">
                  Le document a été transformé en Markdown structuré en seulement <strong>{activeModalJob.elapsed_seconds} seconde(s)</strong> avec une empreinte RAM minimale.
                </p>

                <div className="modal-action-buttons">
                  <button
                    onClick={() => {
                      setActivePreviewId(activeModalJob.job_id);
                      setActiveModalJobId(null);
                    }}
                    className="btn-primary-action"
                  >
                    <FileText size={15} /> Voir l'aperçu complet
                  </button>

                  <a
                    href={`/api/jobs/${activeModalJob.job_id}/download?format=md`}
                    className="btn-subtle"
                    style={{ textDecoration: "none", padding: "0.6rem 1rem", fontSize: "0.9rem" }}
                  >
                    <Download size={15} /> Télécharger (.md)
                  </a>

                  {(activeModalJob.has_images || activeModalJob.has_archive) && (
                    <a
                      href={`/api/jobs/${activeModalJob.job_id}/download?format=zip`}
                      className="btn-subtle"
                      style={{ textDecoration: "none", padding: "0.6rem 1rem", fontSize: "0.9rem" }}
                    >
                      <Archive size={15} /> Télécharger (.zip)
                    </a>
                  )}
                </div>
              </div>
            )}

            {/* État Erreur */}
            {activeModalJob.status === "error" && (
              <div className="modal-body-error">
                <div className="error-halo-icon">
                  <AlertTriangle size={48} color="var(--accent-rose)" />
                </div>

                <h4 className="error-headline">Échec de la conversion</h4>
                <p className="error-subtext">
                  {activeModalJob.error || "Une erreur inattendue est survenue."}
                </p>

                <button
                  onClick={() => setActiveModalJobId(null)}
                  className="btn-subtle"
                  style={{ alignSelf: "center", marginTop: "1rem" }}
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
        <div className="minimal-toast">
          <span>{toastText}</span>
        </div>
      )}
    </div>
  );
}
