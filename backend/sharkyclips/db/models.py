"""
LEONIDEX SQLAlchemy ORM Models for SQLite Canonical Storage
"""
from datetime import datetime, timezone
import json
from typing import List, Dict, Any, Optional
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship

from .database import Base

def utc_now():
    return datetime.now(timezone.utc)

class SourceVideoModel(Base):
    __tablename__ = "source_videos"

    id = Column(Integer, primary_key=True, index=True)
    file_path = Column(String, unique=True, nullable=False)
    filename = Column(String, nullable=False)
    duration = Column(Float, default=0.0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    aspect_ratio = Column(String, default="16:9")
    fps = Column(Float, default=30.0)
    video_codec = Column(String, default="h264")
    has_audio = Column(Boolean, default=True)
    audio_codec = Column(String, nullable=True)
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    sessions = relationship("AnalysisSessionModel", back_populates="video", cascade="all, delete-orphan")

class AnalysisSessionModel(Base):
    __tablename__ = "analysis_sessions"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("source_videos.id"), nullable=False)
    status = Column(String, default="idle") # idle, analyzing, completed, failed
    device_used = Column(String, default="cpu")
    encoder_used = Column(String, default="libx264")
    progress = Column(Float, default=0.0)
    stage = Column(String, default="Idle")
    error_msg = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    video = relationship("SourceVideoModel", back_populates="sessions")
    candidates = relationship("HighlightCandidateModel", back_populates="session", cascade="all, delete-orphan")
    exports = relationship("ExportJobModel", back_populates="session", cascade="all, delete-orphan")

class HighlightCandidateModel(Base):
    __tablename__ = "highlight_candidates"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("analysis_sessions.id"), nullable=False)
    candidate_id = Column(Integer, nullable=False)
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    peak_sec = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    score = Column(Float, nullable=False)
    reason = Column(String, default="")
    signals_json = Column(Text, default="[]")
    transcript_context = Column(Text, default="")
    selected = Column(Boolean, default=True)

    session = relationship("AnalysisSessionModel", back_populates="candidates")

    @property
    def signals(self) -> List[str]:
        try:
            return json.loads(self.signals_json)
        except Exception:
            return []

    @signals.setter
    def signals(self, val: List[str]):
        self.signals_json = json.dumps(val)

class MinimapProfileModel(Base):
    __tablename__ = "minimap_profiles"

    id = Column(Integer, primary_key=True, index=True)
    profile_name = Column(String, unique=True, nullable=False, index=True)
    x_norm = Column(Float, default=0.024)
    y_norm = Column(Float, default=0.755)
    w_norm = Column(Float, default=0.165)
    h_norm = Column(Float, default=0.210)
    is_preset = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)

class DevicePreferenceModel(Base):
    __tablename__ = "device_preferences"

    id = Column(Integer, primary_key=True, index=True)
    processing_device = Column(String, default="auto") # auto, cpu, cuda
    video_encoder = Column(String, default="auto")     # auto, libx264, h264_nvenc, h264_qsv, h264_amf
    whisper_model = Column(String, default="auto")     # auto, large-v3-turbo, medium, small, base, tiny
    updated_at = Column(DateTime, default=utc_now)

class ExportJobModel(Base):
    __tablename__ = "export_jobs"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("analysis_sessions.id"), nullable=True)
    candidate_id = Column(Integer, nullable=False)
    clip_name = Column(String, nullable=False)
    start_sec = Column(Float, nullable=False)
    end_sec = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    status = Column(String, default="pending") # pending, processing, completed, failed
    output_path = Column(String, nullable=True)
    validation_msg = Column(String, nullable=True)
    error_msg = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    session = relationship("AnalysisSessionModel", back_populates="exports")
