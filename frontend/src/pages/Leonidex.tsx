import { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icons";
import { Modal, ProgressBar } from "../components/ui";

interface HardwarePlan {
  detected_cpu: string;
  cpu_physical_cores: number;
  cpu_logical_cores: number;
  ram_total_gb: number;
  has_nvidia_gpu: boolean;
  detected_gpu: string;
  cuda_available: boolean;
  active_execution_device: string;
  active_video_encoder: string;
  active_whisper_model: string;
  available_encoders: string[];
  notes: string[];
}

interface VideoMetadata {
  filename: string;
  file_path: string;
  duration: number;
  duration_str: string;
  width: number;
  height: number;
  aspect_ratio: string;
  fps: number;
  video_codec: string;
  has_audio: boolean;
  audio_codec: string;
  file_size: number;
  file_size_mb: number;
}

interface HighlightCandidate {
  id: number;
  candidate_id: number;
  start_sec: number;
  start_str: string;
  end_sec: number;
  end_str: string;
  peak_sec: number;
  duration: number;
  duration_str: string;
  score: number;
  reason: string;
  signals: Record<string, any>;
  selected: boolean;
}

interface MinimapProfile {
  id: number;
  name: string;
  x_norm: number;
  y_norm: number;
  w_norm: number;
  h_norm: number;
  is_preset: boolean;
}

interface ExportJob {
  id: number;
  candidate_id: number;
  clip_name: string;
  duration_str: string;
  status: string;
  output_path: string | null;
  filename: string | null;
  validation_msg: string | null;
  error_msg: string | null;
}

export default function Leonidex() {
  // 1. Hardware State
  const [hwPlan, setHwPlan] = useState<HardwarePlan | null>(null);
  const [procDevicePref, setProcDevicePref] = useState("auto");
  const [encoderPref, setEncoderPref] = useState("auto");
  const [hwLoading, setHwLoading] = useState(false);

  // 2. Video State
  const [videoMeta, setVideoMeta] = useState<VideoMetadata | null>(null);
  const [videoPathInput, setVideoPathInput] = useState("");
  const [videoLoading, setVideoLoading] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoPlayerRef = useRef<HTMLVideoElement>(null);

  // 3. Highlight Analysis State
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStage, setAnalysisStage] = useState("Idle");
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<HighlightCandidate[]>([]);

  // 4. Minimap State
  const [calX, setCalX] = useState(0.02);
  const [calY, setCalY] = useState(0.72);
  const [calW, setCalW] = useState(0.18);
  const [calH, setCalH] = useState(0.25);
  const [profileName, setProfileName] = useState("GTA V Standard");
  const [profiles, setProfiles] = useState<MinimapProfile[]>([]);
  const [newProfileName, setNewProfileName] = useState("");
  const [cropPreviewNonce, setCropPreviewNonce] = useState(Date.now());
  const [autoDetectConf, setAutoDetectConf] = useState<number | null>(null);

  // 5. Composition State
  const [cropCenterX, setCropCenterX] = useState(0.50);
  const [fitMode, setFitMode] = useState<"crop" | "blur_pad">("crop");
  const [minimapPlacement, setMinimapPlacement] = useState("Top-Center");
  const [minimapScale, setMinimapScale] = useState(1.35);
  const [minimapOffsetX, setMinimapOffsetX] = useState(0);
  const [minimapOffsetY, setMinimapOffsetY] = useState(0);
  const [previewNonce, setPreviewNonce] = useState(Date.now());

  // 6. Export State
  const [isExporting, setIsExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState(0);
  const [exportStage, setExportStage] = useState("Idle");
  const [exportJobs, setExportJobs] = useState<ExportJob[]>([]);
  const [watchingJob, setWatchingJob] = useState<ExportJob | null>(null);

  // Load Initial Data
  useEffect(() => {
    fetchHardwareStatus();
    fetchVideoInfo();
    fetchMinimapProfiles();
    fetchMinimapCalibration();
    fetchCompositionConfig();
  }, []);

  // Poll analysis status
  useEffect(() => {
    let timer: number | undefined;
    if (isAnalyzing) {
      timer = window.setInterval(async () => {
        try {
          const res = await fetch("/api/analysis/status");
          if (res.ok) {
            const data = await res.json();
            setIsAnalyzing(data.is_analyzing);
            setAnalysisProgress(data.progress);
            setAnalysisStage(data.stage);
            setAnalysisError(data.error);
            if (!data.is_analyzing) {
              fetchCandidates();
            }
          }
        } catch {
          // ignore
        }
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isAnalyzing]);

  // Poll export status
  useEffect(() => {
    let timer: number | undefined;
    if (isExporting) {
      timer = window.setInterval(async () => {
        try {
          const res = await fetch("/api/export/status");
          if (res.ok) {
            const data = await res.json();
            setIsExporting(data.is_exporting);
            setExportProgress(data.progress);
            setExportStage(data.stage);
            setExportJobs(data.jobs || []);
          }
        } catch {
          // ignore
        }
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isExporting]);

  // Fetch functions
  const fetchHardwareStatus = async () => {
    try {
      const res = await fetch("/api/hardware/status");
      if (res.ok) {
        const data = await res.json();
        setHwPlan(data);
        setProcDevicePref(data.active_execution_device);
        setEncoderPref(data.active_video_encoder);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleApplyHardware = async () => {
    setHwLoading(true);
    try {
      const res = await fetch("/api/hardware/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          processing_device: procDevicePref,
          video_encoder: encoderPref,
          whisper_model: "auto",
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setHwPlan(data.plan);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setHwLoading(false);
    }
  };

  const fetchVideoInfo = async () => {
    try {
      const res = await fetch("/api/video/info");
      if (res.ok) {
        const data = await res.json();
        if (data.loaded) {
          setVideoMeta(data);
          setVideoPathInput(data.file_path);
          fetchCandidates();
          fetchExportStatus();
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleNativeBrowse = async () => {
    setVideoLoading(true);
    setVideoError(null);
    try {
      const res = await fetch("/api/video/open-dialog", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.success && data.file_path) {
          setVideoPathInput(data.file_path);
          await loadVideoFile(data.file_path);
        }
      }
    } catch (e: any) {
      setVideoError(e.message);
    } finally {
      setVideoLoading(false);
    }
  };

  const loadVideoFile = async (path: string) => {
    setVideoLoading(true);
    setVideoError(null);
    try {
      const res = await fetch("/api/video/load", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_path: path }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to load video");
      }
      const data = await res.json();
      setVideoMeta(data.metadata);
      setCandidates([]);
      setExportJobs([]);
      setCropPreviewNonce(Date.now());
      setPreviewNonce(Date.now());
      if (videoPlayerRef.current) {
        videoPlayerRef.current.load();
      }
    } catch (e: any) {
      setVideoError(e.message);
    } finally {
      setVideoLoading(false);
    }
  };

  const fetchCandidates = async () => {
    try {
      const res = await fetch("/api/analysis/candidates");
      if (res.ok) {
        const data = await res.json();
        setCandidates(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleStartAnalysis = async () => {
    if (!videoMeta) return;
    setIsAnalyzing(true);
    setAnalysisProgress(0);
    setAnalysisStage("Initiating highlight detection pipeline...");
    setAnalysisError(null);
    try {
      await fetch("/api/analysis/start", { method: "POST" });
    } catch (e: any) {
      setAnalysisError(e.message);
      setIsAnalyzing(false);
    }
  };

  const handleCandidatePatch = async (id: number, patch: Partial<HighlightCandidate>) => {
    try {
      const res = await fetch(`/api/analysis/candidate/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (res.ok) {
        fetchCandidates();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSelectAllCandidates = async (select: boolean) => {
    try {
      await fetch(`/api/analysis/select-all?select=${select}`, { method: "POST" });
      fetchCandidates();
    } catch (e) {
      console.error(e);
    }
  };

  const seekVideo = (timeSec: number) => {
    if (videoPlayerRef.current) {
      videoPlayerRef.current.currentTime = timeSec;
      videoPlayerRef.current.play().catch(() => {});
    }
  };

  // Minimap Calibration
  const fetchMinimapCalibration = async () => {
    try {
      const res = await fetch("/api/minimap/calibration");
      if (res.ok) {
        const data = await res.json();
        setCalX(data.x_norm);
        setCalY(data.y_norm);
        setCalW(data.w_norm);
        setCalH(data.h_norm);
        setProfileName(data.profile_name);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const updateCalibration = async (x: number, y: number, w: number, h: number, name = "Custom") => {
    setCalX(x);
    setCalY(y);
    setCalW(w);
    setCalH(h);
    setProfileName(name);
    try {
      await fetch("/api/minimap/calibration", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x_norm: x, y_norm: y, w_norm: w, h_norm: h, profile_name: name }),
      });
      setCropPreviewNonce(Date.now());
      setPreviewNonce(Date.now());
    } catch (e) {
      console.error(e);
    }
  };

  const handleAutoDetectMinimap = async () => {
    try {
      const res = await fetch("/api/minimap/auto-detect", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setAutoDetectConf(data.confidence);
          fetchMinimapCalibration();
          setCropPreviewNonce(Date.now());
          setPreviewNonce(Date.now());
        } else {
          setAutoDetectConf(0);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchMinimapProfiles = async () => {
    try {
      const res = await fetch("/api/minimap/profiles");
      if (res.ok) {
        const data = await res.json();
        setProfiles(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleLoadProfile = async (name: string) => {
    try {
      const res = await fetch(`/api/minimap/profiles/${encodeURIComponent(name)}/load`, { method: "POST" });
      if (res.ok) {
        fetchMinimapCalibration();
        setCropPreviewNonce(Date.now());
        setPreviewNonce(Date.now());
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveProfile = async () => {
    if (!newProfileName.trim()) return;
    try {
      const res = await fetch("/api/minimap/profiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          profile_name: newProfileName.trim(),
          x_norm: calX,
          y_norm: calY,
          w_norm: calW,
          h_norm: calH,
        }),
      });
      if (res.ok) {
        setNewProfileName("");
        fetchMinimapProfiles();
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Composition Config
  const fetchCompositionConfig = async () => {
    try {
      const res = await fetch("/api/preview/config");
      if (res.ok) {
        const data = await res.json();
        setCropCenterX(data.crop_center_x);
        setFitMode(data.fit_mode);
        setMinimapPlacement(data.placement);
        setMinimapScale(data.scale);
        setMinimapOffsetX(data.offset_x);
        setMinimapOffsetY(data.offset_y);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const updateComposition = async (
    cropX: number,
    fMode: "crop" | "blur_pad",
    place: string,
    scale: number,
    offX: number,
    offY: number
  ) => {
    setCropCenterX(cropX);
    setFitMode(fMode);
    setMinimapPlacement(place);
    setMinimapScale(scale);
    setMinimapOffsetX(offX);
    setMinimapOffsetY(offY);
    try {
      await fetch("/api/preview/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          crop_center_x: cropX,
          crop_center_y: 0.5,
          fit_mode: fMode,
          placement: place,
          scale: scale,
          offset_x: offX,
          offset_y: offY,
        }),
      });
      setPreviewNonce(Date.now());
    } catch (e) {
      console.error(e);
    }
  };

  // Export
  const fetchExportStatus = async () => {
    try {
      const res = await fetch("/api/export/status");
      if (res.ok) {
        const data = await res.json();
        setIsExporting(data.is_exporting);
        setExportProgress(data.progress);
        setExportStage(data.stage);
        setExportJobs(data.jobs || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleStartExport = async () => {
    const selectedCount = candidates.filter((c) => c.selected).length;
    if (selectedCount === 0) {
      alert("Please select at least one highlight candidate to export.");
      return;
    }
    setIsExporting(true);
    setExportProgress(0);
    setExportStage("Initializing render engine...");
    try {
      const res = await fetch("/api/export/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        fetchExportStatus();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleCancelExport = async () => {
    try {
      await fetch("/api/export/cancel", { method: "POST" });
    } catch (e) {
      console.error(e);
    }
  };

  const handleOpenOutputFolder = async () => {
    try {
      await fetch("/api/export/open-folder", { method: "POST" });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="leonidex-page" style={{ padding: "24px 32px", maxWidth: 1440, margin: "0 auto" }}>
      {/* HEADER & HARDWARE STATUS BANNER */}
      <div
        className="card"
        style={{
          background: "linear-gradient(135deg, var(--surface) 0%, var(--surface-2) 100%)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--r-lg)",
          padding: 20,
          marginBottom: 24,
          boxShadow: "var(--shadow)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1 style={{ margin: 0, fontSize: "1.75rem", fontWeight: 800, letterSpacing: "-0.02em" }}>
                LEONIDEX
              </h1>
              <span className="chip" style={{ background: "var(--gold-soft)", color: "var(--gold-text)", fontWeight: 700, border: "1px solid var(--gold-line)" }}>
                GTA SHORTS GENERATOR
              </span>
              <span className="chip chip-success" style={{ fontWeight: 600 }}>
                CLEAN 9:16 + HUD
              </span>
            </div>
            <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: "0.9rem" }}>
              Multi-signal local gameplay highlight detection, authentic HUD minimap synchronization, and zero-overlay vertical Shorts rendering.
            </p>
          </div>

          {/* Hardware Selector Box */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: "var(--surface-3)",
              padding: "10px 16px",
              borderRadius: "var(--r-md)",
              border: "1px solid var(--border)",
            }}
          >
            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>
                Whisper Device
              </div>
              <select
                className="select select-sm"
                value={procDevicePref}
                onChange={(e) => setProcDevicePref(e.target.value)}
                style={{ width: 110, marginTop: 4 }}
              >
                <option value="auto">Auto</option>
                <option value="cpu">CPU</option>
                <option value="cuda" disabled={!hwPlan?.cuda_available}>
                  CUDA {hwPlan?.cuda_available ? "" : "(N/A)"}
                </option>
              </select>
            </div>

            <div>
              <div style={{ fontSize: "0.75rem", color: "var(--muted)", textTransform: "uppercase", fontWeight: 700 }}>
                Video Encoder
              </div>
              <select
                className="select select-sm"
                value={encoderPref}
                onChange={(e) => setEncoderPref(e.target.value)}
                style={{ width: 140, marginTop: 4 }}
              >
                <option value="auto">Auto (Best)</option>
                <option value="h264_nvenc">NVENC (NVIDIA)</option>
                <option value="h264_qsv">QSV (Intel)</option>
                <option value="h264_amf">AMF (AMD)</option>
                <option value="libx264">libx264 (CPU)</option>
              </select>
            </div>

            <button
              className="btn btn-primary btn-sm"
              style={{ marginTop: 14 }}
              onClick={handleApplyHardware}
              disabled={hwLoading}
            >
              {hwLoading ? "Saving..." : "Apply Plan"}
            </button>
          </div>
        </div>

        {/* Hardware telemetry chips */}
        {hwPlan && (
          <div style={{ display: "flex", gap: 12, marginTop: 16, flexWrap: "wrap", alignItems: "center" }}>
            <span className="chip" style={{ fontSize: "0.8rem", background: "var(--surface-2)" }}>
              <Icon name="settings" size={14} /> <b>CPU:</b> {hwPlan.detected_cpu} ({hwPlan.cpu_physical_cores}C/{hwPlan.cpu_logical_cores}T, {(hwPlan.ram_total_gb ?? 0).toFixed(0)} GB RAM)
            </span>
            <span className="chip" style={{ fontSize: "0.8rem", background: "var(--surface-2)" }}>
              <Icon name="sparkles" size={14} /> <b>GPU:</b> {hwPlan.detected_gpu || "None"}
            </span>
            <span
              className={`chip ${hwPlan.cuda_available ? "chip-success" : "chip-warn"}`}
              style={{ fontSize: "0.8rem" }}
            >
              <Icon name="check" size={14} /> <b>CUDA:</b> {hwPlan.cuda_available ? "Active" : "CPU Fallback"}
            </span>
            <span className="chip" style={{ fontSize: "0.8rem", background: "var(--chip-bg)", color: "var(--chip-text)" }}>
              <Icon name="film" size={14} /> <b>Active Encoder:</b> {hwPlan.active_video_encoder}
            </span>
            {hwPlan.notes && hwPlan.notes.length > 0 && (
              <span style={{ fontSize: "0.78rem", color: "var(--warn)", fontStyle: "italic", marginLeft: 4 }}>
                ℹ️ {hwPlan.notes.join("; ")}
              </span>
            )}
          </div>
        )}
      </div>

      {/* SECTION 1: VIDEO INGESTION & LOCAL PLAYER */}
      <div className="card" style={{ padding: 20, marginBottom: 24, borderRadius: "var(--r-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
            <Icon name="film" size={20} /> 1. Source Video Ingestion (Local Only)
          </h2>
          <button className="btn btn-primary" onClick={handleNativeBrowse} disabled={videoLoading}>
            <Icon name="upload" size={16} /> {videoLoading ? "Inspecting Video..." : "Browse Video File..."}
          </button>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <input
            className="input"
            type="text"
            placeholder="Or enter absolute path (e.g. C:\CODING FILES\YT CLIP\sample_gta_gameplay.mp4)"
            value={videoPathInput}
            onChange={(e) => setVideoPathInput(e.target.value)}
            style={{ flex: 1 }}
          />
          <button
            className="btn btn-secondary"
            onClick={() => loadVideoFile(videoPathInput)}
            disabled={videoLoading || !videoPathInput}
          >
            Load Path
          </button>
        </div>

        {videoError && (
          <div className="alert alert-danger" style={{ marginBottom: 16 }}>
            <Icon name="alert" size={16} /> {videoError}
          </div>
        )}

        {videoMeta && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
            <div>
              <div
                style={{
                  background: "#000",
                  borderRadius: "var(--r-md)",
                  overflow: "hidden",
                  aspectRatio: "16/9",
                  maxHeight: 280,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <video
                  ref={videoPlayerRef}
                  src="/api/video/stream"
                  controls
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                />
              </div>
            </div>

            <div>
              <h3 style={{ margin: "0 0 10px", fontSize: "1rem", fontWeight: 600 }}>Video File Metadata</h3>
              <table className="table" style={{ width: "100%", fontSize: "0.85rem" }}>
                <tbody>
                  <tr>
                    <td style={{ color: "var(--muted)", width: 140 }}>File Name</td>
                    <td className="mono" style={{ fontWeight: 600 }}>{videoMeta.filename}</td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>Duration</td>
                    <td className="mono">{videoMeta.duration_str || `${Math.floor((videoMeta.duration || 0) / 60)}:${Math.floor((videoMeta.duration || 0) % 60)}`} ({((videoMeta.duration) || 0).toFixed(1)}s)</td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>Resolution</td>
                    <td className="mono">{videoMeta.width} × {videoMeta.height} ({videoMeta.aspect_ratio})</td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>Frame Rate</td>
                    <td className="mono">{((videoMeta.fps) || 30).toFixed(1)} FPS</td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>Video Codec</td>
                    <td className="mono">{videoMeta.video_codec}</td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>Audio Stream</td>
                    <td>
                      {videoMeta.has_audio ? (
                        <span className="chip chip-success" style={{ fontSize: "0.75rem" }}>
                          {(videoMeta.audio_codec || "AUDIO").toUpperCase()} Present
                        </span>
                      ) : (
                        <span className="chip chip-warn" style={{ fontSize: "0.75rem" }}>
                          No Audio Stream
                        </span>
                      )}
                    </td>
                  </tr>
                  <tr>
                    <td style={{ color: "var(--muted)" }}>File Size</td>
                    <td className="mono">{((videoMeta.file_size_mb ?? ((videoMeta.file_size || 0) / (1024 * 1024))) || 0).toFixed(1)} MB</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* SECTION 2 & 3: HIGHLIGHT DETECTION & CANDIDATES */}
      <div className="card" style={{ padding: 20, marginBottom: 24, borderRadius: "var(--r-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="sparkles" size={20} /> 2. GTA Highlight Detection (Audio + Visual Signals)
            </h2>
            <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: "0.85rem" }}>
              Scans audio energy surges, explosions/impacts, and visual motion/flash deltas to extract authentic gameplay action.
            </p>
          </div>
          <button
            className="btn btn-primary"
            onClick={handleStartAnalysis}
            disabled={!videoMeta || isAnalyzing}
          >
            <Icon name="sparkles" size={16} />
            {isAnalyzing ? "Analyzing Video..." : "Run Highlight Detection"}
          </button>
        </div>

        {/* Progress Tracker */}
        {(isAnalyzing || analysisProgress > 0) && (
          <div
            style={{
              background: "var(--surface-2)",
              padding: 16,
              borderRadius: "var(--r-md)",
              marginBottom: 20,
              border: "1px solid var(--border)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: "0.88rem" }}>
              <span style={{ fontWeight: 600 }}>{analysisStage}</span>
              <span className="mono" style={{ fontWeight: 700 }}>
                {Math.round(analysisProgress * 100)}%
              </span>
            </div>
            <ProgressBar value={analysisProgress} />
            {analysisError && (
              <div style={{ marginTop: 8, color: "var(--danger)", fontSize: "0.85rem" }}>
                Error: {analysisError}
              </div>
            )}
          </div>
        )}

        {/* Candidates Table */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 600 }}>
              Detected Highlight Candidates ({candidates.length})
            </h3>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleSelectAllCandidates(true)}
                disabled={candidates.length === 0}
              >
                Select All
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => handleSelectAllCandidates(false)}
                disabled={candidates.length === 0}
              >
                Deselect All
              </button>
            </div>
          </div>

          {candidates.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "32px 0",
                color: "var(--muted)",
                background: "var(--surface-2)",
                borderRadius: "var(--r-md)",
              }}
            >
              No highlight candidates generated yet. Click "Run Highlight Detection" above to analyze video.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table className="table" style={{ width: "100%", fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th style={{ width: 40, textAlign: "center" }}>Export</th>
                    <th style={{ width: 50 }}>#</th>
                    <th style={{ width: 80 }}>Score</th>
                    <th style={{ width: 140 }}>Start</th>
                    <th style={{ width: 140 }}>End</th>
                    <th style={{ width: 80 }}>Duration</th>
                    <th>Detection Rationale</th>
                    <th style={{ width: 100, textAlign: "right" }}>Preview</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c) => (
                    <tr key={c.id} style={{ background: c.selected ? "var(--surface-2)" : "transparent" }}>
                      <td style={{ textAlign: "center" }}>
                        <input
                          type="checkbox"
                          checked={c.selected}
                          onChange={(e) => handleCandidatePatch(c.id, { selected: e.target.checked })}
                        />
                      </td>
                      <td className="mono" style={{ fontWeight: 600 }}>#{c.candidate_id}</td>
                      <td>
                        <span
                          className="chip"
                          style={{
                            fontWeight: 700,
                            background: c.score >= 80 ? "var(--success-soft)" : "var(--chip-bg)",
                            color: c.score >= 80 ? "var(--success)" : "var(--chip-text)",
                          }}
                        >
                          {Math.round(c.score)}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <button
                            className="btn btn-ghost icon-btn"
                            style={{ padding: 2, height: 22, width: 22 }}
                            title="-1.0s"
                            onClick={() => handleCandidatePatch(c.id, { start_sec: Math.max(0, c.start_sec - 1.0) })}
                          >
                            -
                          </button>
                          <span className="mono" style={{ fontSize: "0.8rem" }}>{c.start_str}</span>
                          <button
                            className="btn btn-ghost icon-btn"
                            style={{ padding: 2, height: 22, width: 22 }}
                            title="+1.0s"
                            onClick={() => handleCandidatePatch(c.id, { start_sec: c.start_sec + 1.0 })}
                          >
                            +
                          </button>
                        </div>
                      </td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                          <button
                            className="btn btn-ghost icon-btn"
                            style={{ padding: 2, height: 22, width: 22 }}
                            title="-1.0s"
                            onClick={() => handleCandidatePatch(c.id, { end_sec: Math.max(c.start_sec + 1.0, c.end_sec - 1.0) })}
                          >
                            -
                          </button>
                          <span className="mono" style={{ fontSize: "0.8rem" }}>{c.end_str}</span>
                          <button
                            className="btn btn-ghost icon-btn"
                            style={{ padding: 2, height: 22, width: 22 }}
                            title="+1.0s"
                            onClick={() => handleCandidatePatch(c.id, { end_sec: c.end_sec + 1.0 })}
                          >
                            +
                          </button>
                        </div>
                      </td>
                      <td className="mono">{c.duration_str}</td>
                      <td style={{ color: "var(--muted)", maxWidth: 350 }}>{c.reason}</td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => seekVideo(c.start_sec)}
                          title="Jump player to clip start"
                        >
                          <Icon name="play" size={13} /> Seek
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* SECTION 4 & 5: MINIMAP CALIBRATION & 9:16 COMPOSITION */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
        {/* SECTION 4: MINIMAP CALIBRATION */}
        <div className="card" style={{ padding: 20, borderRadius: "var(--r-lg)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="scan" size={18} /> 4. HUD Minimap Calibration
            </h2>
            <button className="btn btn-secondary btn-sm" onClick={handleAutoDetectMinimap} disabled={!videoMeta}>
              Auto-Detect HUD
            </button>
          </div>

          {autoDetectConf !== null && (
            <div
              className={`chip ${autoDetectConf > 0.4 ? "chip-success" : "chip-warn"}`}
              style={{ marginBottom: 12, display: "inline-flex" }}
            >
              Auto-detect Confidence: {(autoDetectConf * 100).toFixed(0)}%
            </div>
          )}

          {/* Preset Selector */}
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 16 }}>
            <label style={{ fontSize: "0.85rem", color: "var(--muted)", fontWeight: 600 }}>Profile Preset:</label>
            <select
              className="select select-sm"
              style={{ flex: 1 }}
              value={profileName}
              onChange={(e) => {
                const name = e.target.value;
                setProfileName(name);
                handleLoadProfile(name);
              }}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.name}>
                  {p.name} {p.is_preset ? "(Preset)" : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Coordinate Sliders */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
                <span>X Offset</span>
                <span className="mono">{(((calX ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="0.5"
                step="0.005"
                value={calX}
                onChange={(e) => updateCalibration(parseFloat(e.target.value), calY, calW, calH, "Custom")}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
                <span>Y Offset</span>
                <span className="mono">{(((calY ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min="0.4"
                max="0.9"
                step="0.005"
                value={calY}
                onChange={(e) => updateCalibration(calX, parseFloat(e.target.value), calW, calH, "Custom")}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
                <span>Crop Width</span>
                <span className="mono">{(((calW ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min="0.08"
                max="0.4"
                step="0.005"
                value={calW}
                onChange={(e) => updateCalibration(calX, calY, parseFloat(e.target.value), calH, "Custom")}
                style={{ width: "100%" }}
              />
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem" }}>
                <span>Crop Height</span>
                <span className="mono">{(((calH ?? 0) * 100)).toFixed(1)}%</span>
              </div>
              <input
                type="range"
                min="0.1"
                max="0.45"
                step="0.005"
                value={calH}
                onChange={(e) => updateCalibration(calX, calY, calW, parseFloat(e.target.value), "Custom")}
                style={{ width: "100%" }}
              />
            </div>
          </div>

          {/* Minimap Crop Preview Box */}
          <div style={{ display: "flex", gap: 16, alignItems: "center", background: "var(--surface-2)", padding: 12, borderRadius: "var(--r-md)" }}>
            <div
              style={{
                width: 140,
                height: 140,
                background: "#000",
                borderRadius: "var(--r-sm)",
                overflow: "hidden",
                border: "2px solid var(--gold-line)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {videoMeta ? (
                <img
                  src={`/api/minimap/crop-preview?_t=${cropPreviewNonce}`}
                  alt="Extracted Minimap HUD"
                  style={{ width: "100%", height: "100%", objectFit: "contain" }}
                />
              ) : (
                <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>No Frame</span>
              )}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>Extracted HUD Crop</div>
              <div style={{ fontSize: "0.78rem", color: "var(--muted)", margin: "4px 0 10px" }}>
                Authentic extracted minimap crop synchronized to source gameplay.
              </div>

              {/* Save Profile */}
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  className="input input-sm"
                  type="text"
                  placeholder="Profile Name..."
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                />
                <button
                  className="btn btn-secondary btn-sm"
                  onClick={handleSaveProfile}
                  disabled={!newProfileName.trim()}
                >
                  Save Profile
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* SECTION 5: 9:16 COMPOSITION & LIVE PREVIEW */}
        <div className="card" style={{ padding: 20, borderRadius: "var(--r-lg)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="phone" size={18} /> 5. 9:16 Composition & Live Preview
            </h2>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setPreviewNonce(Date.now())}
              disabled={!videoMeta}
            >
              <Icon name="refresh" size={14} /> Refresh Frame
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 180px", gap: 20, alignItems: "start" }}>
            {/* Composition Controls */}
            <div>
              {/* Horizontal Crop Placement */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", marginBottom: 4 }}>
                  <span style={{ fontWeight: 600 }}>Horizontal Crop Framing</span>
                  <span className="mono">{Math.round(cropCenterX * 100)}%</span>
                </div>
                <input
                  type="range"
                  min="0.15"
                  max="0.85"
                  step="0.01"
                  value={cropCenterX}
                  onChange={(e) =>
                    updateComposition(
                      parseFloat(e.target.value),
                      fitMode,
                      minimapPlacement,
                      minimapScale,
                      minimapOffsetX,
                      minimapOffsetY
                    )
                  }
                  style={{ width: "100%" }}
                />
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.72rem", color: "var(--muted)" }}>
                  <span>Left (Crosshair)</span>
                  <span>Center (50%)</span>
                  <span>Right (Player)</span>
                </div>
              </div>

              {/* Fit Mode */}
              <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: "0.8rem", fontWeight: 600, display: "block", marginBottom: 4 }}>
                  Vertical Fit Mode:
                </label>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    className={`btn btn-sm ${fitMode === "crop" ? "btn-primary" : "btn-secondary"}`}
                    onClick={() =>
                      updateComposition(
                        cropCenterX,
                        "crop",
                        minimapPlacement,
                        minimapScale,
                        minimapOffsetX,
                        minimapOffsetY
                      )
                    }
                  >
                    Crop (Full 9:16 Fill)
                  </button>
                  <button
                    className={`btn btn-sm ${fitMode === "blur_pad" ? "btn-primary" : "btn-secondary"}`}
                    onClick={() =>
                      updateComposition(
                        cropCenterX,
                        "blur_pad",
                        minimapPlacement,
                        minimapScale,
                        minimapOffsetX,
                        minimapOffsetY
                      )
                    }
                  >
                    Blurred Background
                  </button>
                </div>
              </div>

              {/* Minimap Placement & Scale */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                <div>
                  <label style={{ fontSize: "0.78rem", fontWeight: 600, display: "block", marginBottom: 4 }}>
                    Minimap Placement:
                  </label>
                  <select
                    className="select select-sm"
                    value={minimapPlacement}
                    onChange={(e) =>
                      updateComposition(
                        cropCenterX,
                        fitMode,
                        e.target.value,
                        minimapScale,
                        minimapOffsetX,
                        minimapOffsetY
                      )
                    }
                  >
                    <option value="Top-Center">Top-Center</option>
                    <option value="Top-Left">Top-Left</option>
                    <option value="Top-Right">Top-Right</option>
                    <option value="Bottom-Center">Bottom-Center</option>
                  </select>
                </div>

                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", marginBottom: 4 }}>
                    <span style={{ fontWeight: 600 }}>HUD Scale</span>
                    <span className="mono">{((minimapScale ?? 1.35)).toFixed(2)}x</span>
                  </div>
                  <input
                    type="range"
                    min="0.8"
                    max="2.2"
                    step="0.05"
                    value={minimapScale}
                    onChange={(e) =>
                      updateComposition(
                        cropCenterX,
                        fitMode,
                        minimapPlacement,
                        parseFloat(e.target.value),
                        minimapOffsetX,
                        minimapOffsetY
                      )
                    }
                    style={{ width: "100%" }}
                  />
                </div>
              </div>

              <div
                style={{
                  fontSize: "0.75rem",
                  color: "var(--muted)",
                  background: "var(--surface-2)",
                  padding: 8,
                  borderRadius: "var(--r-sm)",
                }}
              >
                🔒 Strict compliance: Clean vertical composition with synchronized authentic minimap. Subtitles, audio dubs, and creative text are explicitly disabled.
              </div>
            </div>

            {/* 9:16 Live Preview Image */}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div
                style={{
                  width: 170,
                  height: 302,
                  background: "#000",
                  borderRadius: "var(--r-md)",
                  overflow: "hidden",
                  border: "2px solid var(--border-strong)",
                  boxShadow: "var(--shadow-pop)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {videoMeta ? (
                  <img
                    src={`/api/preview/render?_t=${previewNonce}`}
                    alt="9:16 Live Preview"
                    style={{ width: "100%", height: "100%", objectFit: "contain" }}
                  />
                ) : (
                  <span style={{ fontSize: "0.75rem", color: "var(--muted)" }}>9:16 Preview</span>
                )}
              </div>
              <span style={{ fontSize: "0.72rem", color: "var(--muted)", marginTop: 6 }}>
                1080 × 1920 (9:16)
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 6: CLEAN SHORTS BATCH EXPORT & VALIDATION */}
      <div className="card" style={{ padding: 20, borderRadius: "var(--r-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
              <Icon name="download" size={20} /> 6. Clean Shorts Export & FFprobe Validation
            </h2>
            <p style={{ margin: "4px 0 0", color: "var(--muted)", fontSize: "0.85rem" }}>
              Exports vertical MP4 clips (1080×1920) directly to local workspace with automated FFprobe compliance verification.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            {isExporting ? (
              <button className="btn btn-secondary" onClick={handleCancelExport}>
                <Icon name="x" size={16} /> Cancel Export
              </button>
            ) : (
              <button
                className="btn btn-primary"
                onClick={handleStartExport}
                disabled={!videoMeta || candidates.filter((c) => c.selected).length === 0}
              >
                <Icon name="film" size={16} /> Export Selected (
                {candidates.filter((c) => c.selected).length}) Shorts
              </button>
            )}
            <button className="btn btn-secondary" onClick={handleOpenOutputFolder}>
              <Icon name="file" size={16} /> Open Folder
            </button>
          </div>
        </div>

        {/* Export Progress Bar */}
        {(isExporting || exportProgress > 0) && (
          <div
            style={{
              background: "var(--surface-2)",
              padding: 16,
              borderRadius: "var(--r-md)",
              marginBottom: 20,
              border: "1px solid var(--border)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: "0.88rem" }}>
              <span style={{ fontWeight: 600 }}>{exportStage}</span>
              <span className="mono" style={{ fontWeight: 700 }}>
                {Math.round(exportProgress * 100)}%
              </span>
            </div>
            <ProgressBar value={exportProgress} />
          </div>
        )}

        {/* Export Jobs Table */}
        {exportJobs.length === 0 ? (
          <div
            style={{
              textAlign: "center",
              padding: "24px 0",
              color: "var(--muted)",
              background: "var(--surface-2)",
              borderRadius: "var(--r-md)",
            }}
          >
            No export jobs submitted yet. Select desired candidates above and click "Export Selected Shorts".
          </div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="table" style={{ width: "100%", fontSize: "0.85rem" }}>
              <thead>
                <tr>
                  <th style={{ width: 60 }}>#</th>
                  <th>Clip Name</th>
                  <th style={{ width: 90 }}>Duration</th>
                  <th style={{ width: 110 }}>Status</th>
                  <th>FFprobe Validation</th>
                  <th style={{ width: 110, textAlign: "right" }}>Player</th>
                </tr>
              </thead>
              <tbody>
                {exportJobs.map((j) => (
                  <tr key={j.id}>
                    <td className="mono" style={{ fontWeight: 600 }}>#{j.candidate_id}</td>
                    <td className="mono" style={{ fontWeight: 600 }}>{j.clip_name}</td>
                    <td className="mono">{j.duration_str}</td>
                    <td>
                      <span
                        className={`chip ${
                          j.status === "completed"
                            ? "chip-success"
                            : j.status === "failed"
                            ? "chip-danger"
                            : "chip-warn"
                        }`}
                        style={{ fontSize: "0.75rem", textTransform: "capitalize" }}
                      >
                        {j.status}
                      </span>
                    </td>
                    <td>
                      {j.status === "completed" && (
                        <span style={{ fontSize: "0.78rem", color: "var(--success)" }}>
                          ✓ {j.validation_msg || "1080x1920 (9:16) yuv420p verified"}
                        </span>
                      )}
                      {j.status === "failed" && (
                        <span style={{ fontSize: "0.78rem", color: "var(--danger)" }}>
                          ✗ {j.error_msg || "Render failed"}
                        </span>
                      )}
                      {j.status === "processing" && (
                        <span style={{ fontSize: "0.78rem", color: "var(--muted)" }}>
                          Rendering with {hwPlan?.active_video_encoder || "encoder"}...
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {j.status === "completed" && (
                        <button
                          className="btn btn-secondary btn-sm"
                          onClick={() => setWatchingJob(j)}
                        >
                          <Icon name="play" size={13} /> Watch Short
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* WATCH SHORT MODAL */}
      {watchingJob && (
        <Modal
          title={`Watch Clean Short: ${watchingJob.clip_name}`}
          onClose={() => setWatchingJob(null)}
        >
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "10px 0" }}>
            <div
              style={{
                width: 320,
                height: 568,
                background: "#000",
                borderRadius: "var(--r-md)",
                overflow: "hidden",
                border: "2px solid var(--border-strong)",
                boxShadow: "var(--shadow-pop)",
              }}
            >
              <video
                src={`/api/export/stream/${watchingJob.id}`}
                controls
                autoPlay
                style={{ width: "100%", height: "100%", objectFit: "contain" }}
              />
            </div>
            <div style={{ marginTop: 12, textAlign: "center", fontSize: "0.85rem", color: "var(--muted)" }}>
              {watchingJob.validation_msg || "Verified clean 9:16 vertical Short"}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
