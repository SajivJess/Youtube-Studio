"""
LEONIDEX Production Test Suite
Verifies end-to-end functionality of LEONIDEX integration:
- SQLite persistence and schema
- Dual-execution hardware manager and CUDA fallback
- Video inspection and probe
- Minimap extraction, presets, and calibration
- Multi-signal GTA highlight detection (with & without audio)
- Clean 9:16 Shorts composition and FFprobe verification
- FastAPI REST endpoints
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sharkyclips.db.database import get_db, SessionLocal, init_db, DB_PATH
from sharkyclips.db.models import (
    SourceVideoModel,
    AnalysisSessionModel,
    HighlightCandidateModel,
    MinimapProfileModel,
    DevicePreferenceModel,
    ExportJobModel,
)
from sharkyclips.hardware_selector import HardwareManager, HardwareStatus
from sharkyclips.minimap import (
    MinimapCalibration,
    crop_minimap_image,
    extract_frame_at,
    auto_detect_minimap,
    seed_minimap_presets_in_db,
)
from sharkyclips.render_shorts import (
    ShortsCompositionConfig,
    probe_video_meta,
    render_preview_frame,
    render_clean_short,
    validate_export,
)
from sharkyclips.highlights.gta import GTAHighlightDetector, GTAHighlightCandidate
from sharkyclips.web.app import app

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_GTA = DATA_DIR / "sample_gta_gameplay.mp4"
SAMPLE_NO_AUDIO = DATA_DIR / "sample_no_audio_720p.mp4"


@pytest.fixture(scope="module")
def client():
    init_db()
    seed_minimap_presets_in_db()
    with TestClient(app) as c:
        yield c


# =====================================================================
# 1. DATABASE TESTS
# =====================================================================
class TestLeonidexDatabase:
    def test_database_initialization(self):
        init_db()
        assert DB_PATH.exists()
        db = SessionLocal()
        try:
            # Check presets exist
            presets = db.query(MinimapProfileModel).filter_by(is_preset=True).all()
            preset_names = [p.profile_name for p in presets]
            assert any("GTA V Standard" in p for p in preset_names)
            assert any("GTA V Expanded Radar" in p for p in preset_names)
            assert any("GTA IV Standard" in p for p in preset_names)
        finally:
            db.close()

    def test_video_and_session_persistence(self):
        db = SessionLocal()
        try:
            video = SourceVideoModel(
                file_path="C:/test/sample.mp4",
                filename="sample.mp4",
                duration=60.0,
                width=1920,
                height=1080,
                aspect_ratio="16:9",
                fps=60.0,
                video_codec="h264",
                has_audio=True,
                audio_codec="aac",
                file_size=1048576,
            )
            db.add(video)
            db.commit()
            db.refresh(video)
            assert video.id is not None

            session = AnalysisSessionModel(
                video_id=video.id,
                status="analyzing",
                progress=0.5,
                stage="Audio analysis",
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            assert session.id is not None

            cand = HighlightCandidateModel(
                session_id=session.id,
                candidate_id=1,
                start_sec=10.0,
                end_sec=25.0,
                peak_sec=18.0,
                duration=15.0,
                score=88.5,
                reason="Audio spike + high motion",
                signals_json=json.dumps({"audio_energy": 0.9, "motion": 0.8}),
                selected=True,
            )
            db.add(cand)
            db.commit()
            db.refresh(cand)
            assert cand.id is not None
            assert cand.signals["audio_energy"] == 0.9

            # Clean up
            db.delete(cand)
            db.delete(session)
            db.delete(video)
            db.commit()
        finally:
            db.close()


# =====================================================================
# 2. HARDWARE MANAGER & DUAL-EXECUTION ARCHITECTURE
# =====================================================================
class TestHardwareSelector:
    def test_hardware_probe(self):
        hw_mgr = HardwareManager.get_instance()
        info = hw_mgr.probe_hardware()
        assert info.cpu_name != ""
        assert info.cpu_physical_cores > 0
        assert info.cpu_logical_cores > 0
        assert info.ram_total_gb > 0.0

    def test_plan_resolution_and_preference_override(self):
        hw_mgr = HardwareManager.get_instance()
        # Force CPU mode preference
        hw_mgr.set_preferences(processing_device="cpu", video_encoder="libx264")
        plan = hw_mgr.resolve_hardware_plan()
        assert plan.active_execution_device == "cpu"
        assert plan.active_video_encoder == "libx264"
        assert plan.active_device_preference == "cpu"

        # Reset to auto
        hw_mgr.set_preferences(processing_device="auto", video_encoder="auto")
        auto_plan = hw_mgr.resolve_hardware_plan()
        assert auto_plan.active_execution_device in ("cpu", "cuda")
        assert len(auto_plan.available_encoders) > 0


# =====================================================================
# 3. VIDEO METADATA PROBE
# =====================================================================
class TestVideoProbe:
    def test_probe_sample_gta_video(self):
        assert SAMPLE_GTA.exists(), f"Missing {SAMPLE_GTA}"
        meta = probe_video_meta(str(SAMPLE_GTA))
        assert meta["filename"] == "sample_gta_gameplay.mp4"
        assert meta["width"] == 1920
        assert meta["height"] == 1080
        assert meta["aspect_ratio"] == "16:9"
        assert meta["duration"] > 0
        assert meta["has_audio"] is True
        assert meta["audio_codec"] is not None

    def test_probe_video_without_audio(self):
        assert SAMPLE_NO_AUDIO.exists(), f"Missing {SAMPLE_NO_AUDIO}"
        meta = probe_video_meta(str(SAMPLE_NO_AUDIO))
        assert meta["filename"] == "sample_no_audio_720p.mp4"
        assert meta["width"] == 1280
        assert meta["height"] == 720
        assert meta["has_audio"] is False
        assert meta["audio_codec"] is None


# =====================================================================
# 4. MINIMAP CALIBRATION & EXTRACTION
# =====================================================================
class TestMinimapExtraction:
    def test_frame_extraction(self):
        frame = extract_frame_at(str(SAMPLE_GTA), 1.0)
        assert frame is not None
        assert frame.shape == (1080, 1920, 3)

    def test_minimap_crop(self):
        frame = extract_frame_at(str(SAMPLE_GTA), 1.0)
        cal = MinimapCalibration(x_norm=0.02, y_norm=0.72, w_norm=0.18, h_norm=0.25)
        crop = crop_minimap_image(frame, cal)
        assert crop is not None
        assert crop.shape[0] > 50
        assert crop.shape[1] > 50

    def test_auto_detect_minimap(self):
        frame = extract_frame_at(str(SAMPLE_GTA), 1.0)
        cal, conf = auto_detect_minimap(frame)
        assert cal is not None
        assert conf > 0.0
        assert 0.0 <= cal.x_norm <= 0.2
        assert 0.6 <= cal.y_norm <= 0.95


# =====================================================================
# 5. MULTI-SIGNAL GTA HIGHLIGHT DETECTION
# =====================================================================
class TestHighlightDetection:
    def test_detect_highlights_on_sample_gta(self):
        meta = probe_video_meta(str(SAMPLE_GTA))
        detector = GTAHighlightDetector()
        stages_seen = []

        def cb(pct, stage):
            stages_seen.append(stage)

        cands = detector.detect_highlights(
            str(SAMPLE_GTA),
            meta["duration"],
            meta["has_audio"],
            progress_cb=cb,
        )
        assert len(cands) > 0
        assert any("Audio" in s or "energy" in s for s in stages_seen)
        best = cands[0]
        assert best.duration >= 5.0
        assert best.score >= 0.0
        assert best.reason != ""
        assert any("Audio" in s for s in best.signals)

    def test_detect_highlights_without_audio_stream(self):
        meta = probe_video_meta(str(SAMPLE_NO_AUDIO))
        detector = GTAHighlightDetector()
        cands = detector.detect_highlights(
            str(SAMPLE_NO_AUDIO),
            meta["duration"],
            meta["has_audio"],
        )
        assert len(cands) > 0
        # Should gracefully fall back to visual detection
        for c in cands:
            assert any("Visual" in s for s in c.signals)


# =====================================================================
# 6. CLEAN 9:16 SHORTS RENDERING & STRICT VALIDATION
# =====================================================================
class TestShortsRendering:
    def test_preview_frame_generation(self):
        frame = extract_frame_at(str(SAMPLE_GTA), 2.0)
        cal = MinimapCalibration()
        cfg = ShortsCompositionConfig(fit_mode="crop", minimap_placement="Top-Center", minimap_scale=1.2)
        preview = render_preview_frame(frame, cal, cfg, preview_h=540)
        assert preview is not None
        # 9:16 aspect: height 540 -> width ~304
        assert preview.shape[0] == 540
        assert abs(preview.shape[1] - 304) <= 2

    def test_render_clean_short_and_validate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "test_clean_short.mp4"
            cal = MinimapCalibration()
            cfg = ShortsCompositionConfig(fit_mode="crop", minimap_placement="Top-Center")

            success, msg = render_clean_short(
                source_path=str(SAMPLE_GTA),
                output_path=str(out_path),
                start_sec=2.0,
                end_sec=6.0,
                cal=cal,
                cfg=cfg,
                encoder_name="libx264",
            )
            assert success is True, f"Render failed: {msg}"
            assert out_path.exists()

            # Strict FFprobe validation
            v_ok, v_msg = validate_export(str(out_path))
            assert v_ok is True, f"Validation failed: {v_msg}"
            assert "1080x1920" in v_msg
            assert "yuv420p" in v_msg


# =====================================================================
# 7. FASTAPI REST API INTEGRATION
# =====================================================================
class TestLeonidexApi:
    def test_hardware_endpoints(self, client):
        r = client.get("/api/hardware/status")
        assert r.status_code == 200
        data = r.json()
        assert "cpu_name" in data
        assert "active_video_encoder" in data

        r2 = client.post(
            "/api/hardware/preferences",
            json={"processing_device": "cpu", "video_encoder": "libx264"},
        )
        assert r2.status_code == 200
        assert r2.json()["plan"]["active_execution_device"] == "cpu"

    def test_video_load_and_info(self, client):
        r = client.post("/api/video/load", json={"file_path": str(SAMPLE_GTA)})
        assert r.status_code == 200
        meta = r.json()["metadata"]
        assert meta["filename"] == "sample_gta_gameplay.mp4"

        r_info = client.get("/api/video/info")
        assert r_info.status_code == 200
        assert r_info.json()["loaded"] is True

    def test_video_frame_and_stream(self, client):
        r_frame = client.get("/api/video/frame?t=1.0")
        assert r_frame.status_code == 200
        assert r_frame.headers["content-type"] == "image/jpeg"

        # HTTP 206 Partial Content Stream
        r_stream = client.get("/api/video/stream", headers={"Range": "bytes=0-1024"})
        assert r_stream.status_code == 206
        assert "Content-Range" in r_stream.headers

    def test_minimap_calibration_and_profiles(self, client):
        r_cal = client.get("/api/minimap/calibration")
        assert r_cal.status_code == 200

        r_up = client.post(
            "/api/minimap/calibration",
            json={"x_norm": 0.05, "y_norm": 0.75, "w_norm": 0.15, "h_norm": 0.20, "profile_name": "TestProfile"},
        )
        assert r_up.status_code == 200
        assert r_up.json()["calibration"]["x_norm"] == 0.05

        r_crop = client.get("/api/minimap/crop-preview")
        assert r_crop.status_code == 200
        assert r_crop.headers["content-type"] == "image/jpeg"

        r_profiles = client.get("/api/minimap/profiles")
        assert r_profiles.status_code == 200
        assert len(r_profiles.json()) >= 3

    def test_preview_config_and_render(self, client):
        r_cfg = client.get("/api/preview/config")
        assert r_cfg.status_code == 200

        r_set = client.post(
            "/api/preview/config",
            json={
                "crop_center_x": 0.52,
                "crop_center_y": 0.50,
                "fit_mode": "crop",
                "placement": "Top-Center",
                "scale": 1.4,
                "offset_x": 0,
                "offset_y": 0,
            },
        )
        assert r_set.status_code == 200
        assert r_set.json()["config"]["crop_center_x"] == 0.52

        r_render = client.get("/api/preview/render?t=1.0")
        assert r_render.status_code == 200
        assert r_render.headers["content-type"] == "image/jpeg"

    def test_candidate_patch(self, client):
        db = SessionLocal()
        try:
            cand = HighlightCandidateModel(
                session_id=1,
                candidate_id=99,
                start_sec=10.0,
                end_sec=20.0,
                peak_sec=15.0,
                duration=10.0,
                score=75.0,
                reason="Test candidate",
                signals_json="{}",
                selected=False,
            )
            db.add(cand)
            db.commit()
            db.refresh(cand)
            cand_id = cand.id
        finally:
            db.close()

        r_patch = client.patch(
            f"/api/analysis/candidate/{cand_id}",
            json={"start_sec": 9.0, "end_sec": 21.0, "selected": True},
        )
        assert r_patch.status_code == 200
        assert r_patch.json()["start_sec"] == 9.0
        assert r_patch.json()["selected"] is True

        # Clean up
        db = SessionLocal()
        try:
            c = db.query(HighlightCandidateModel).filter_by(id=cand_id).first()
            if c:
                db.delete(c)
                db.commit()
        finally:
            db.close()
