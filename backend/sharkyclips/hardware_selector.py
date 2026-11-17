"""
LEONIDEX Hardware Selector & Device Manager
Handles runtime hardware detection (CPU vs NVIDIA GPU/CUDA), Whisper inference device selection,
encoder probing (NVENC, QSV, AMF, libx264), and fallback logic for CPU-only servers.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from . import hardware, render
from .db.database import SessionLocal
from .db.models import DevicePreferenceModel

@dataclass
class HardwareStatus:
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    ram_available_gb: float
    gpus: List[Dict[str, Any]]
    has_nvidia: bool
    cuda_available: bool
    cuda_device_count: int
    cuda_error: Optional[str]
    available_encoders: List[Dict[str, Any]] # [{name, label, hardware, working}]
    active_device_preference: str           # "auto", "cpu", "cuda"
    active_encoder_preference: str          # "auto", "libx264", "h264_nvenc", etc.
    active_execution_device: str            # resolved: "cuda" or "cpu"
    active_video_encoder: str               # resolved: "libx264", "h264_nvenc", etc.
    whisper_model: str                      # resolved: "large-v3-turbo", "medium", "small", etc.
    compute_type: str                       # resolved: "float16", "int8", etc.
    fallback_warning: Optional[str] = None

class HardwareManager:
    _instance: Optional[HardwareManager] = None

    def __init__(self):
        self._cached_hw: Optional[hardware.HardwareInfo] = None
        self._encoder_tests: Dict[str, bool] = {}

    @classmethod
    def get_instance(cls) -> HardwareManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def probe_hardware(self) -> hardware.HardwareInfo:
        if self._cached_hw is None:
            self._cached_hw = hardware.detect_hardware()
        return self._cached_hw

    def probe_encoders(self) -> List[Dict[str, Any]]:
        """Probe each known video encoder with a short test to verify actual hardware functionality."""
        encoders_info = []
        for name, enc in render.ENCODERS.items():
            if name not in self._encoder_tests:
                # Test encoder with 0.5s probe
                try:
                    working = render.test_encoder(name)
                except Exception:
                    working = (name == "libx264")
                self._encoder_tests[name] = working
            else:
                working = self._encoder_tests[name]

            encoders_info.append({
                "name": name,
                "label": enc.label,
                "hardware": enc.hardware,
                "working": working
            })
        return encoders_info

    def get_preferences(self) -> Tuple[str, str, str]:
        """Fetch current device preferences from SQLite."""
        db = SessionLocal()
        try:
            pref = db.query(DevicePreferenceModel).first()
            if not pref:
                pref = DevicePreferenceModel(
                    processing_device="auto",
                    video_encoder="auto",
                    whisper_model="auto"
                )
                db.add(pref)
                db.commit()
                db.refresh(pref)
            return (pref.processing_device, pref.video_encoder, pref.whisper_model)
        finally:
            db.close()

    def set_preferences(self, processing_device: str, video_encoder: str, whisper_model: str = "auto"):
        """Save device preferences to SQLite."""
        db = SessionLocal()
        try:
            pref = db.query(DevicePreferenceModel).first()
            if not pref:
                pref = DevicePreferenceModel()
                db.add(pref)
            pref.processing_device = processing_device.lower()
            pref.video_encoder = video_encoder.lower()
            pref.whisper_model = whisper_model.lower()
            db.commit()
        finally:
            db.close()

    def resolve_hardware_plan(self) -> HardwareStatus:
        """
        Derive the complete runtime execution plan based on:
        1. Actual backend hardware detected (CPU, RAM, GPU, CUDA).
        2. SQLite user preferences (auto, cpu, cuda).
        3. Automatic fallback logic when CUDA is missing or fails smoke test.
        """
        hw = self.probe_hardware()
        encoders = self.probe_encoders()
        dev_pref, enc_pref, model_pref = self.get_preferences()

        # Check CUDA accessibility
        cuda_count = hardware.cuda_device_count()
        cuda_ok = cuda_count > 0 and hw.best_nvidia is not None
        cuda_err = None
        if hw.best_nvidia is None:
            cuda_err = "No NVIDIA GPU detected on this machine"
        elif cuda_count == 0:
            cuda_err = "NVIDIA GPU found but CUDA drivers / cuDNN DLLs not accessible by CTranslate2"

        # Resolve processing device
        fallback_warning = None
        if dev_pref == "cuda":
            if cuda_ok:
                active_device = "cuda"
            else:
                active_device = "cpu"
                fallback_warning = f"CUDA was requested, but {cuda_err}. Falling back to CPU processing."
        elif dev_pref == "cpu":
            active_device = "cpu"
        else: # auto
            if cuda_ok and hw.best_nvidia and hw.best_nvidia.vram_gb >= 2.0:
                active_device = "cuda"
            else:
                active_device = "cpu"

        # Resolve Whisper model and compute type
        if active_device == "cuda" and hw.best_nvidia:
            vram = hw.best_nvidia.vram_gb
            compute_type = hardware.cuda_compute_for(vram)
            if model_pref == "auto":
                if vram >= 6.0:
                    whisper_model = "large-v3-turbo"
                elif vram >= 3.0:
                    whisper_model = "medium"
                else:
                    whisper_model = "small"
            else:
                whisper_model = model_pref
        else:
            active_device = "cpu"
            compute_type = "int8"
            if model_pref == "auto":
                whisper_model = "small" if hw.ram_total_gb >= 6.0 else "base"
            else:
                whisper_model = model_pref

        # Resolve video encoder
        working_encoders = {e["name"]: e["working"] for e in encoders}
        if enc_pref != "auto" and working_encoders.get(enc_pref, False):
            active_encoder = enc_pref
        else:
            # Pick first verified working hardware encoder, fallback to libx264
            active_encoder = "libx264"
            if active_device == "cuda" and working_encoders.get("h264_nvenc", False):
                active_encoder = "h264_nvenc"
            else:
                for candidate in ["h264_nvenc", "h264_qsv", "h264_amf"]:
                    if working_encoders.get(candidate, False):
                        active_encoder = candidate
                        break

        # Compile status
        gpu_list = []
        if hw.best_nvidia:
            gpu_list.append({
                "name": hw.best_nvidia.name,
                "vram_total_mb": hw.best_nvidia.vram_total_mb,
                "vram_gb": round(hw.best_nvidia.vram_gb, 1),
                "type": "NVIDIA"
            })
        for o_gpu in hw.other_gpus:
            gpu_list.append({
                "name": o_gpu,
                "type": "Integrated / Other"
            })

        return HardwareStatus(
            cpu_name=hw.cpu_name,
            cpu_cores=hw.cpu_physical_cores,
            cpu_threads=hw.cpu_logical_cores,
            ram_total_gb=round(hw.ram_total_gb, 1),
            ram_available_gb=round(hw.ram_available_gb, 1),
            gpus=gpu_list,
            has_nvidia=bool(hw.best_nvidia),
            cuda_available=cuda_ok,
            cuda_device_count=cuda_count,
            cuda_error=cuda_err,
            available_encoders=encoders,
            active_device_preference=dev_pref,
            active_encoder_preference=enc_pref,
            active_execution_device=active_device,
            active_video_encoder=active_encoder,
            whisper_model=whisper_model,
            compute_type=compute_type,
            fallback_warning=fallback_warning
        )
