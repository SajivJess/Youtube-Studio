"""
LEONIDEX REST API Router for SharkyClips FastAPI Backend
Provides all endpoints for video inspection, SQLite persistence, hardware management,
minimap calibration, 9:16 preview rendering, and clean Shorts export.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, BackgroundTasks
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import DEFAULT_WORKSPACE
from ..db.database import get_db, SessionLocal
from ..db.models import (
    SourceVideoModel,
    AnalysisSessionModel,
    HighlightCandidateModel,
    MinimapProfileModel,
    DevicePreferenceModel,
    ExportJobModel
)
from ..minimap import (
    MinimapCalibration,
    extract_frame_at,
    crop_minimap_image,
    auto_detect_minimap,
    seed_minimap_presets_in_db
)
from ..hardware_selector import HardwareManager
from ..render_shorts import (
    ShortsCompositionConfig,
    probe_video_meta,
    render_preview_frame,
    render_clean_short
)
from ..highlights.gta import GTAHighlightDetector, GTAHighlightCandidate

router = APIRouter(prefix="/api", tags=["leonidex"])

# Make sure presets are seeded
seed_minimap_presets_in_db()

# Global in-memory state for active session
class ActiveState:
    video_id: Optional[int] = None
    session_id: Optional[int] = None
    current_video_path: Optional[str] = None
    current_meta: Optional[Dict[str, Any]] = None
    representative_frame: Optional[np.ndarray] = None
    calibration: MinimapCalibration = MinimapCalibration()
    composition: ShortsCompositionConfig = ShortsCompositionConfig()

    is_analyzing: bool = False
    analysis_progress: float = 0.0
    analysis_stage: str = "Idle"
    analysis_error: Optional[str] = None

    is_exporting: bool = False
    export_progress: float = 0.0
    export_stage: str = "Idle"
    export_cancel_event = threading.Event()

active_state = ActiveState()

# Schemas
class LoadVideoReq(BaseModel):
    file_path: str

class CalibrationReq(BaseModel):
    x_norm: float
    y_norm: float
    w_norm: float
    h_norm: float
    profile_name: Optional[str] = "Custom"

class SaveProfileReq(BaseModel):
    profile_name: str
    x_norm: float
    y_norm: float
    w_norm: float
    h_norm: float

class CompositionReq(BaseModel):
    crop_center_x: float = 0.50
    crop_center_y: float = 0.50
    fit_mode: str = "crop"
    placement: str = "Top-Center"
    scale: float = 1.35
    offset_x: int = 0
    offset_y: int = 0

class CandidatePatchReq(BaseModel):
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    selected: Optional[bool] = None

class HardwarePrefReq(BaseModel):
    processing_device: str # auto, cpu, cuda
    video_encoder: str     # auto, libx264, h264_nvenc, h264_qsv, h264_amf
    whisper_model: Optional[str] = "auto"

class ExportReq(BaseModel):
    output_dir: Optional[str] = None

# -------------------------------------------------------------
# 1. HARDWARE STATUS & DEVICE SELECTION
# -------------------------------------------------------------
@router.get("/hardware/status")
def get_hardware_status():
    hw_mgr = HardwareManager.get_instance()
    plan = hw_mgr.resolve_hardware_plan()
    d = plan.__dict__.copy()
    d["detected_cpu"] = plan.cpu_name
    d["cpu_physical_cores"] = plan.cpu_cores
    d["cpu_logical_cores"] = plan.cpu_threads
    d["detected_gpu"] = plan.gpus[0]["name"] if plan.gpus else "None"
    notes = []
    if plan.fallback_warning:
        notes.append(plan.fallback_warning)
    d["notes"] = notes
    return d

@router.post("/hardware/preferences")
def set_hardware_preferences(req: HardwarePrefReq):
    hw_mgr = HardwareManager.get_instance()
    hw_mgr.set_preferences(req.processing_device, req.video_encoder, req.whisper_model or "auto")
    plan = hw_mgr.resolve_hardware_plan()
    d = plan.__dict__.copy()
    d["detected_cpu"] = plan.cpu_name
    d["cpu_physical_cores"] = plan.cpu_cores
    d["cpu_logical_cores"] = plan.cpu_threads
    d["detected_gpu"] = plan.gpus[0]["name"] if plan.gpus else "None"
    notes = []
    if plan.fallback_warning:
        notes.append(plan.fallback_warning)
    d["notes"] = notes
    return {"success": True, "plan": d}

# -------------------------------------------------------------
# 2. VIDEO INGESTION & STREAMING (LOCAL ONLY)
# -------------------------------------------------------------
@router.post("/video/open-dialog")
def open_native_file_dialog():
    """Opens native Windows file picker dialog."""
    import tkinter as tk
    from tkinter import filedialog
    selected_path = None

    def ask_file():
        nonlocal selected_path
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_path = filedialog.askopenfilename(
            title="Select Gameplay Video File",
            filetypes=[
                ("Video Files", "*.mp4 *.mkv *.mov *.avi *.webm"),
                ("MP4 Videos", "*.mp4"),
                ("MKV Videos", "*.mkv"),
                ("QuickTime MOV", "*.mov"),
                ("All Files", "*.*")
            ]
        )
        root.destroy()

    t = threading.Thread(target=ask_file)
    t.start()
    t.join(timeout=60)
    return {"success": bool(selected_path), "file_path": selected_path}

@router.post("/video/load")
def load_video_endpoint(req: LoadVideoReq, db: Session = Depends(get_db)):
    p = Path(req.file_path).resolve()
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {req.file_path}")

    try:
        meta = probe_video_meta(str(p))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Video inspection failed: {e}")

    # Record in SQLite
    video_rec = db.query(SourceVideoModel).filter_by(file_path=str(p)).first()
    if not video_rec:
        video_rec = SourceVideoModel(
            file_path=str(p),
            filename=meta["filename"],
            duration=meta["duration"],
            width=meta["width"],
            height=meta["height"],
            aspect_ratio=meta["aspect_ratio"],
            fps=meta["fps"],
            video_codec=meta["video_codec"],
            has_audio=meta["has_audio"],
            audio_codec=meta["audio_codec"],
            file_size=meta["file_size"]
        )
        db.add(video_rec)
        db.commit()
        db.refresh(video_rec)

    # Create new analysis session
    session_rec = AnalysisSessionModel(
        video_id=video_rec.id,
        status="idle",
        progress=0.0,
        stage="Loaded video"
    )
    db.add(session_rec)
    db.commit()
    db.refresh(session_rec)

    active_state.video_id = video_rec.id
    active_state.session_id = session_rec.id
    active_state.current_video_path = str(p)
    active_state.current_meta = meta

    # Extract representative frame
    sample_t = min(5.0, meta["duration"] * 0.15) if meta["duration"] > 0 else 0.0
    frame = extract_frame_at(str(p), sample_t)
    if frame is not None:
        active_state.representative_frame = frame

    return {
        "session_id": session_rec.id,
        "metadata": meta
    }

@router.get("/video/info")
def get_video_info():
    if not active_state.current_meta:
        return {"loaded": False}
    return {
        "loaded": True,
        "session_id": active_state.session_id,
        **active_state.current_meta
    }

@router.get("/video/frame")
def get_video_frame(t: float = Query(0.0)):
    if not active_state.current_video_path:
        raise HTTPException(status_code=400, detail="No video loaded")

    frame = extract_frame_at(active_state.current_video_path, t)
    if frame is None:
        frame = active_state.representative_frame
    if frame is None:
        raise HTTPException(status_code=500, detail="Could not extract frame")

    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ret, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return Response(content=buf.tobytes(), media_type="image/jpeg")

@router.get("/video/stream")
def stream_source_video(request: Request):
    """HTTP 206 Partial Content range streaming for HTML5 video player."""
    if not active_state.current_video_path:
        raise HTTPException(status_code=404, detail="No video loaded")

    file_p = Path(active_state.current_video_path)
    file_size = file_p.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1

        def iter_chunks():
            with open(file_p, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(left, 1024 * 1024))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iter_chunks(), status_code=206, headers=headers)

    return FileResponse(file_p, media_type="video/mp4")

# -------------------------------------------------------------
# 3. MULTI-SIGNAL HIGHLIGHT DETECTION
# -------------------------------------------------------------
@router.post("/analysis/start")
def start_highlight_analysis(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not active_state.current_meta or not active_state.session_id:
        raise HTTPException(status_code=400, detail="No video loaded")

    if active_state.is_analyzing:
        return {"status": "already_running"}

    active_state.is_analyzing = True
    active_state.analysis_progress = 0.0
    active_state.analysis_stage = "Starting highlight detection..."
    active_state.analysis_error = None

    def worker(session_id: int, v_path: str, duration: float, has_audio: bool):
        job_db = SessionLocal()
        try:
            hw_mgr = HardwareManager.get_instance()
            plan = hw_mgr.resolve_hardware_plan()

            # Record plan in session
            job_db.query(AnalysisSessionModel).filter_by(id=session_id).update({
                "status": "analyzing",
                "device_used": plan.active_execution_device,
                "encoder_used": plan.active_video_encoder
            })
            job_db.commit()

            detector = GTAHighlightDetector()
            def progress_cb(pct, msg):
                active_state.analysis_progress = pct
                active_state.analysis_stage = msg

            cands = detector.detect_highlights(v_path, duration, has_audio, progress_cb=progress_cb)

            # Save in SQLite
            job_db.query(HighlightCandidateModel).filter_by(session_id=session_id).delete()
            for c in cands:
                rec = HighlightCandidateModel(
                    session_id=session_id,
                    candidate_id=c.candidate_id,
                    start_sec=c.start_sec,
                    end_sec=c.end_sec,
                    peak_sec=c.peak_sec,
                    duration=c.duration,
                    score=c.score,
                    reason=c.reason,
                    signals_json=json.dumps(c.signals),
                    selected=c.selected
                )
                job_db.add(rec)

            job_db.query(AnalysisSessionModel).filter_by(id=session_id).update({
                "status": "completed",
                "progress": 1.0,
                "stage": f"Completed: {len(cands)} highlight moments detected"
            })
            job_db.commit()

            active_state.is_analyzing = False
            active_state.analysis_progress = 1.0
            active_state.analysis_stage = f"Analysis complete: {len(cands)} highlight moments detected."
        except Exception as e:
            active_state.is_analyzing = False
            active_state.analysis_error = str(e)
            active_state.analysis_stage = f"Analysis failed: {e}"
            job_db.query(AnalysisSessionModel).filter_by(id=session_id).update({
                "status": "failed",
                "error_msg": str(e)
            })
            job_db.commit()
        finally:
            job_db.close()

    background_tasks.add_task(
        worker,
        active_state.session_id,
        active_state.current_video_path,
        active_state.current_meta["duration"],
        active_state.current_meta["has_audio"]
    )
    return {"status": "started"}

@router.get("/analysis/status")
def get_analysis_status(db: Session = Depends(get_db)):
    count = 0
    if active_state.session_id:
        count = db.query(HighlightCandidateModel).filter_by(session_id=active_state.session_id).count()

    return {
        "is_analyzing": active_state.is_analyzing,
        "progress": round(active_state.analysis_progress, 2),
        "stage": active_state.analysis_stage,
        "error": active_state.analysis_error,
        "candidate_count": count
    }

@router.get("/analysis/candidates")
def get_candidates(db: Session = Depends(get_db)):
    if not active_state.session_id:
        return []
    recs = db.query(HighlightCandidateModel).filter_by(session_id=active_state.session_id).order_by(HighlightCandidateModel.candidate_id).all()

    def format_time(sec):
        m, s = int(sec // 60), int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{m:02d}:{s:02d}.{ms:03d}"

    return [{
        "id": r.id,
        "candidate_id": r.candidate_id,
        "start_sec": r.start_sec,
        "start_str": format_time(r.start_sec),
        "end_sec": r.end_sec,
        "end_str": format_time(r.end_sec),
        "peak_sec": r.peak_sec,
        "duration": r.duration,
        "duration_str": f"{r.duration:.1f}s",
        "score": r.score,
        "reason": r.reason,
        "signals": r.signals,
        "selected": r.selected
    } for r in recs]

@router.patch("/analysis/candidate/{id}")
def update_candidate(id: int, patch: CandidatePatchReq, db: Session = Depends(get_db)):
    cand = db.query(HighlightCandidateModel).filter_by(id=id).first()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if patch.start_sec is not None:
        cand.start_sec = max(0.0, patch.start_sec)
    if patch.end_sec is not None:
        cand.end_sec = max(cand.start_sec + 0.5, patch.end_sec)
    cand.duration = round(cand.end_sec - cand.start_sec, 2)

    if patch.selected is not None:
        cand.selected = patch.selected

    db.commit()
    db.refresh(cand)
    return {"id": cand.id, "start_sec": cand.start_sec, "end_sec": cand.end_sec, "selected": cand.selected}

@router.post("/analysis/select-all")
def select_all_candidates(select: bool = Query(True), db: Session = Depends(get_db)):
    if active_state.session_id:
        db.query(HighlightCandidateModel).filter_by(session_id=active_state.session_id).update({"selected": select})
        db.commit()
    return {"success": True, "selected": select}

# -------------------------------------------------------------
# 4. MINIMAP CALIBRATION & PROFILES
# -------------------------------------------------------------
@router.get("/minimap/calibration")
def get_minimap_calibration():
    cal = active_state.calibration
    return {
        "x_norm": cal.x_norm,
        "y_norm": cal.y_norm,
        "w_norm": cal.w_norm,
        "h_norm": cal.h_norm,
        "profile_name": cal.profile_name
    }

@router.post("/minimap/calibration")
def update_minimap_calibration(cal: CalibrationReq):
    active_state.calibration.x_norm = cal.x_norm
    active_state.calibration.y_norm = cal.y_norm
    active_state.calibration.w_norm = cal.w_norm
    active_state.calibration.h_norm = cal.h_norm
    active_state.calibration.profile_name = cal.profile_name or "Custom"
    active_state.calibration.clamp()
    return {"success": True, "calibration": get_minimap_calibration()}

@router.get("/minimap/crop-preview")
def get_minimap_crop_preview():
    if active_state.representative_frame is None:
        raise HTTPException(status_code=400, detail="No frame loaded")

    crop = crop_minimap_image(active_state.representative_frame, active_state.calibration)
    if crop is None or crop.size == 0:
        raise HTTPException(status_code=500, detail="Crop failed")

    bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
    ret, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")

@router.post("/minimap/auto-detect")
def run_minimap_auto_detect():
    if active_state.representative_frame is None:
        raise HTTPException(status_code=400, detail="No frame loaded")

    cal, conf = auto_detect_minimap(active_state.representative_frame)
    if cal:
        active_state.calibration = cal
        return {"success": True, "confidence": round(conf, 2), "calibration": get_minimap_calibration()}
    return {"success": False, "confidence": 0.0}

@router.get("/minimap/profiles")
def list_profiles(db: Session = Depends(get_db)):
    recs = db.query(MinimapProfileModel).all()
    return [{
        "id": r.id,
        "name": r.profile_name,
        "x_norm": r.x_norm,
        "y_norm": r.y_norm,
        "w_norm": r.w_norm,
        "h_norm": r.h_norm,
        "is_preset": r.is_preset
    } for r in recs]

@router.post("/minimap/profiles")
def save_profile_endpoint(req: SaveProfileReq, db: Session = Depends(get_db)):
    existing = db.query(MinimapProfileModel).filter_by(profile_name=req.profile_name).first()
    if existing:
        existing.x_norm = req.x_norm
        existing.y_norm = req.y_norm
        existing.w_norm = req.w_norm
        existing.h_norm = req.h_norm
    else:
        existing = MinimapProfileModel(
            profile_name=req.profile_name,
            x_norm=req.x_norm,
            y_norm=req.y_norm,
            w_norm=req.w_norm,
            h_norm=req.h_norm,
            is_preset=False
        )
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return {"success": True, "profile_id": existing.id}

@router.post("/minimap/profiles/{name}/load")
def load_profile_by_name(name: str, db: Session = Depends(get_db)):
    rec = db.query(MinimapProfileModel).filter_by(profile_name=name).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Profile not found")

    active_state.calibration = MinimapCalibration(
        x_norm=rec.x_norm,
        y_norm=rec.y_norm,
        w_norm=rec.w_norm,
        h_norm=rec.h_norm,
        profile_name=rec.profile_name
    )
    return {"success": True, "calibration": get_minimap_calibration()}

# -------------------------------------------------------------
# 5. 9:16 COMPOSITION & LIVE PREVIEW
# -------------------------------------------------------------
@router.get("/preview/config")
def get_preview_config():
    c = active_state.composition
    return {
        "crop_center_x": c.crop_center_x,
        "crop_center_y": c.crop_center_y,
        "fit_mode": c.fit_mode,
        "placement": c.minimap_placement,
        "scale": c.minimap_scale,
        "offset_x": c.minimap_offset_x,
        "offset_y": c.minimap_offset_y
    }

@router.post("/preview/config")
def set_preview_config(req: CompositionReq):
    c = active_state.composition
    c.crop_center_x = req.crop_center_x
    c.crop_center_y = req.crop_center_y
    c.fit_mode = req.fit_mode
    c.minimap_placement = req.placement
    c.minimap_scale = req.scale
    c.minimap_offset_x = req.offset_x
    c.minimap_offset_y = req.offset_y
    return {"success": True, "config": get_preview_config()}

@router.get("/preview/render")
def render_live_preview(t: float = Query(0.0)):
    frame = None
    if active_state.current_video_path:
        frame = extract_frame_at(active_state.current_video_path, t)
    if frame is None:
        frame = active_state.representative_frame
    if frame is None:
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

    preview_rgb = render_preview_frame(
        frame,
        active_state.calibration,
        active_state.composition,
        preview_h=540
    )
    bgr = cv2.cvtColor(preview_rgb, cv2.COLOR_RGB2BGR)
    ret, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return Response(content=buf.tobytes(), media_type="image/jpeg")

# -------------------------------------------------------------
# 6. CLEAN SHORTS BATCH EXPORT & VALIDATION
# -------------------------------------------------------------
@router.post("/export/start")
def start_batch_export(req: ExportReq, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if not active_state.current_meta or not active_state.session_id:
        raise HTTPException(status_code=400, detail="No video loaded")

    if active_state.is_exporting:
        return {"status": "already_exporting"}

    candidates_db = db.query(HighlightCandidateModel).filter_by(
        session_id=active_state.session_id, selected=True
    ).all()

    if not candidates_db:
        raise HTTPException(status_code=400, detail="No clips selected for export")

    out_dir = Path(req.output_dir) if req.output_dir else (DEFAULT_WORKSPACE / "outputs")
    src_base = Path(active_state.current_meta["filename"]).stem
    target_dir = out_dir / src_base
    target_dir.mkdir(parents=True, exist_ok=True)

    export_records = []
    for c in candidates_db:
        rec = ExportJobModel(
            session_id=active_state.session_id,
            candidate_id=c.candidate_id,
            clip_name=f"{src_base}_Short_{c.candidate_id:03d}",
            start_sec=c.start_sec,
            end_sec=c.end_sec,
            duration=c.duration,
            status="pending"
        )
        db.add(rec)
        export_records.append(rec)
    db.commit()

    active_state.is_exporting = True
    active_state.export_cancel_event.clear()
    active_state.export_progress = 0.0
    active_state.export_stage = f"Starting export of {len(export_records)} clips..."

    def export_worker(jobs_info: List[Dict[str, Any]], session_id: int, v_path: str, cal: MinimapCalibration, cfg: ShortsCompositionConfig, out_folder: Path):
        job_db = SessionLocal()
        try:
            hw_mgr = HardwareManager.get_instance()
            plan = hw_mgr.resolve_hardware_plan()
            encoder = plan.active_video_encoder

            total = len(jobs_info)
            for idx, j in enumerate(jobs_info):
                if active_state.export_cancel_event.is_set():
                    job_db.query(ExportJobModel).filter_by(id=j["db_id"]).update({
                        "status": "failed",
                        "error_msg": "Canceled by user"
                    })
                    job_db.commit()
                    continue

                active_state.export_progress = idx / total
                active_state.export_stage = f"Rendering clip {idx+1}/{total} using {encoder}..."

                job_db.query(ExportJobModel).filter_by(id=j["db_id"]).update({"status": "processing"})
                job_db.commit()

                out_file = out_folder / f"{j['clip_name']}.mp4"
                success, msg = render_clean_short(
                    source_path=v_path,
                    output_path=str(out_file),
                    start_sec=j["start_sec"],
                    end_sec=j["end_sec"],
                    cal=cal,
                    cfg=cfg,
                    encoder_name=encoder,
                    cancel_event=active_state.export_cancel_event
                )

                job_db.query(ExportJobModel).filter_by(id=j["db_id"]).update({
                    "status": "completed" if success else "failed",
                    "output_path": str(out_file) if success else None,
                    "validation_msg": msg if success else None,
                    "error_msg": None if success else msg
                })
                job_db.commit()

            active_state.is_exporting = False
            active_state.export_progress = 1.0
            active_state.export_stage = "All export jobs completed."
        finally:
            job_db.close()

    jobs_data = [{
        "db_id": r.id,
        "clip_name": r.clip_name,
        "start_sec": r.start_sec,
        "end_sec": r.end_sec
    } for r in export_records]

    background_tasks.add_task(
        export_worker,
        jobs_data,
        active_state.session_id,
        active_state.current_video_path,
        active_state.calibration,
        active_state.composition,
        target_dir
    )
    return {"status": "started", "jobs_count": len(export_records)}

@router.get("/export/status")
def get_export_status(db: Session = Depends(get_db)):
    jobs_out = []
    if active_state.session_id:
        recs = db.query(ExportJobModel).filter_by(session_id=active_state.session_id).order_by(ExportJobModel.id.desc()).all()
        for r in recs:
            jobs_out.append({
                "id": r.id,
                "candidate_id": r.candidate_id,
                "clip_name": r.clip_name,
                "duration_str": f"{r.duration:.1f}s",
                "status": r.status,
                "output_path": r.output_path,
                "filename": Path(r.output_path).name if r.output_path else None,
                "validation_msg": r.validation_msg,
                "error_msg": r.error_msg
            })

    return {
        "is_exporting": active_state.is_exporting,
        "progress": round(active_state.export_progress, 2),
        "stage": active_state.export_stage,
        "jobs": jobs_out
    }

@router.post("/export/cancel")
def cancel_export():
    active_state.export_cancel_event.set()
    return {"status": "cancelling"}

@router.post("/export/open-folder")
def open_export_folder():
    out_dir = DEFAULT_WORKSPACE / "outputs"
    if active_state.current_meta:
        src_base = Path(active_state.current_meta["filename"]).stem
        target = out_dir / src_base
        if target.exists():
            out_dir = target
    out_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        os.startfile(str(out_dir))
    else:
        subprocess.run(["xdg-open", str(out_dir)])
    return {"success": True, "path": str(out_dir)}

@router.get("/export/stream/{job_id}")
def stream_exported_short(job_id: int, request: Request, db: Session = Depends(get_db)):
    job_rec = db.query(ExportJobModel).filter_by(id=job_id).first()
    if not job_rec or not job_rec.output_path:
        raise HTTPException(status_code=404, detail="Job not found")

    p = Path(job_rec.output_path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="File does not exist")

    file_size = p.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        byte_range = range_header.replace("bytes=", "").split("-")
        start = int(byte_range[0])
        end = int(byte_range[1]) if byte_range[1] else file_size - 1
        length = end - start + 1

        def iter_chunks():
            with open(p, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(left, 1024 * 1024))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        }
        return StreamingResponse(iter_chunks(), status_code=206, headers=headers)

    return FileResponse(p, media_type="video/mp4")
