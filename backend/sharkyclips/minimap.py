"""
LEONIDEX Authentic Minimap Extraction & Calibration Module
Extracts HUD minimap directly from original source video frames prior to vertical cropping.
Maintains frame synchronization and normalized resolution-independent positioning.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any
import numpy as np
import cv2

GTA_MINIMAP_PRESETS: Dict[str, Dict[str, float]] = {
    "GTA V Standard (Bottom-Left)": {
        "x": 0.024,
        "y": 0.755,
        "w": 0.165,
        "h": 0.210,
    },
    "GTA V Expanded Radar (Bottom-Left)": {
        "x": 0.020,
        "y": 0.680,
        "w": 0.220,
        "h": 0.290,
    },
    "GTA IV Standard (Bottom-Left)": {
        "x": 0.030,
        "y": 0.770,
        "w": 0.150,
        "h": 0.190,
    },
}

@dataclass
class MinimapCalibration:
    x_norm: float = 0.024
    y_norm: float = 0.755
    w_norm: float = 0.165
    h_norm: float = 0.210
    profile_name: str = "GTA V Standard (Bottom-Left)"

    def clamp(self):
        """Clamp normalized coordinates within [0.0, 1.0]."""
        self.x_norm = max(0.0, min(0.95, self.x_norm))
        self.y_norm = max(0.0, min(0.95, self.y_norm))
        self.w_norm = max(0.02, min(1.0 - self.x_norm, self.w_norm))
        self.h_norm = max(0.02, min(1.0 - self.y_norm, self.h_norm))

    def to_pixel_box(self, src_w: int, src_h: int) -> Tuple[int, int, int, int]:
        """Convert normalized coordinates to integer pixel box (x, y, w, h), even dimensions."""
        self.clamp()
        x = int(round(self.x_norm * src_w))
        y = int(round(self.y_norm * src_h))
        w = int(round(self.w_norm * src_w))
        h = int(round(self.h_norm * src_h))

        x = max(0, min(src_w - 2, x))
        y = max(0, min(src_h - 2, y))
        w = max(4, min(src_w - x, w))
        h = max(4, min(src_h - y, h))

        if w % 2 != 0:
            w = max(4, w - 1)
        if h % 2 != 0:
            h = max(4, h - 1)

        return (x, y, w, h)

    @classmethod
    def from_pixel_box(
        cls, x: int, y: int, w: int, h: int, src_w: int, src_h: int, profile_name: str = "Custom"
    ) -> "MinimapCalibration":
        cal = cls(
            x_norm=float(x) / src_w,
            y_norm=float(y) / src_h,
            w_norm=float(w) / src_w,
            h_norm=float(h) / src_h,
            profile_name=profile_name,
        )
        cal.clamp()
        return cal

def extract_frame_at(video_path: str, timestamp_sec: float) -> Optional[np.ndarray]:
    """Extract a single full-resolution frame from video at timestamp_sec using FFmpeg or OpenCV."""
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-ss", str(max(0.0, timestamp_sec)),
        "-i", str(video_path),
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "png",
        "pipe:1"
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        raw_img = proc.stdout
        if raw_img:
            nparr = np.frombuffer(raw_img, np.uint8)
            bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        pass

    # OpenCV fallback
    try:
        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp_sec * 1000.0))
        ret, bgr = cap.read()
        cap.release()
        if ret and bgr is not None:
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        pass
    return None

def crop_minimap_image(frame_rgb: np.ndarray, cal: MinimapCalibration) -> np.ndarray:
    """Crop the minimap region from the given full frame array."""
    h, w, _ = frame_rgb.shape
    bx, by, bw, bh = cal.to_pixel_box(w, h)
    return frame_rgb[by:by+bh, bx:bx+bw]

def auto_detect_minimap(frame_rgb: np.ndarray) -> Tuple[Optional[MinimapCalibration], float]:
    """Auto-detect candidate GTA circular radar HUD in bottom-left corner."""
    h, w, _ = frame_rgb.shape
    roi_x = 0
    roi_y = int(0.55 * h)
    roi_w = int(0.35 * w)
    roi_h = int(0.45 * h)

    roi = frame_rgb[roi_y:roi_y+roi_h, roi_x:roi_x+roi_w]
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)

    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=50,
        param1=100,
        param2=35,
        minRadius=int(roi_h * 0.15),
        maxRadius=int(roi_h * 0.45)
    )

    if circles is not None and len(circles) > 0:
        c = circles[0][0]
        cx, cy, r = int(c[0]), int(c[1]), int(c[2])
        bx = max(0, roi_x + cx - r - 8)
        by = max(0, roi_y + cy - r - 8)
        bw = (r * 2) + 16
        bh = (r * 2) + int(r * 0.35) + 16

        cal = MinimapCalibration.from_pixel_box(bx, by, bw, bh, w, h, profile_name="Auto-Detected Circle Radar")
        return cal, 0.85

    default_cal = MinimapCalibration(profile_name="GTA V Standard (Bottom-Left)")
    return default_cal, 0.50

def seed_minimap_presets_in_db():
    """Seeds GTA minimap presets into SQLite if missing."""
    from .db.database import SessionLocal
    from .db.models import MinimapProfileModel
    db = SessionLocal()
    try:
        for name, coords in GTA_MINIMAP_PRESETS.items():
            existing = db.query(MinimapProfileModel).filter_by(profile_name=name).first()
            if not existing:
                rec = MinimapProfileModel(
                    profile_name=name,
                    x_norm=coords["x"],
                    y_norm=coords["y"],
                    w_norm=coords["w"],
                    h_norm=coords["h"],
                    is_preset=True
                )
                db.add(rec)
        db.commit()
    finally:
        db.close()
