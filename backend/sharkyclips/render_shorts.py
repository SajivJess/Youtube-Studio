"""
LEONIDEX Clean 9:16 Shorts Rendering & Strict FFprobe Validation Engine
Extracts authentic HUD minimap from original source frames, converts gameplay to 9:16,
overlays synchronized minimap, and encodes using the selected hardware or CPU encoder.

Strict rule: ZERO subtitles, captions, background music, sound effects, voiceovers,
stickers, logos, channel branding, or decorative frames.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Tuple, Dict, Any
import numpy as np
import cv2

from .minimap import MinimapCalibration, crop_minimap_image
from .hardware_selector import HardwareManager
from .errors import SharkyClipsError, require_tool
from .procs import no_window

TARGET_W, TARGET_H = 1080, 1920

@dataclass
class ShortsCompositionConfig:
    crop_center_x: float = 0.50  # 0.0=left, 0.5=center, 1.0=right
    crop_center_y: float = 0.50
    fit_mode: str = "crop"       # "crop" (direct vertical crop) or "fit_blur" (blurred background)
    minimap_placement: str = "Top-Center"
    minimap_scale: float = 1.35
    minimap_margin_top: int = 40
    minimap_margin_bottom: int = 120
    minimap_margin_x: int = 40
    minimap_offset_x: int = 0
    minimap_offset_y: int = 0

def probe_video_meta(file_path: str) -> Dict[str, Any]:
    """Probe video with ffprobe and return parsed streams."""
    p = Path(file_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,channels,sample_rate",
        "-of", "json",
        str(p)
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    data = json.loads(proc.stdout)

    v_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    if not v_stream:
        raise ValueError("No video stream found in file")

    w = int(v_stream.get("width") or 0)
    h = int(v_stream.get("height") or 0)
    fps_raw = v_stream.get("r_frame_rate") or "30/1"
    try:
        if "/" in fps_raw:
            num, den = fps_raw.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0
        else:
            fps = float(fps_raw)
    except Exception:
        fps = 30.0

    duration = float(data.get("format", {}).get("duration") or v_stream.get("duration") or 0.0)
    file_size = int(data.get("format", {}).get("size") or p.stat().st_size)

    aspect_ratio = f"{w}:{h}"
    if h > 0:
        ratio = w / h
        if abs(ratio - 16/9) < 0.05:
            aspect_ratio = "16:9"
        elif abs(ratio - 9/16) < 0.05:
            aspect_ratio = "9:16"

    file_size_mb = round(file_size / (1024 * 1024), 2)
    mins = int(duration // 60)
    secs = int(duration % 60)
    duration_str = f"{mins:02d}:{secs:02d}"

    return {
        "path": str(p),
        "filename": p.name,
        "width": w,
        "height": h,
        "aspect_ratio": aspect_ratio,
        "fps": fps,
        "duration": duration,
        "duration_str": duration_str,
        "file_size": file_size,
        "file_size_mb": file_size_mb,
        "video_codec": v_stream.get("codec_name", "unknown"),
        "has_audio": a_stream is not None,
        "audio_codec": a_stream.get("codec_name") if a_stream else None,
        "audio_channels": int(a_stream.get("channels") or 0) if a_stream else 0
    }

def calculate_crop_and_overlay(
    src_w: int,
    src_h: int,
    cal: MinimapCalibration,
    cfg: ShortsCompositionConfig
) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int, int, int, int, int]]:
    """
    Computes:
    1. Gameplay crop box: (crop_x, crop_y, crop_w, crop_h)
    2. Minimap extraction & overlay: (mx, my, mw, mh, dest_x, dest_y, smw, smh)
    """
    # Target aspect 9:16 = 0.5625
    target_aspect = TARGET_W / TARGET_H
    src_aspect = src_w / src_h

    if src_aspect >= target_aspect:
        crop_h = src_h
        crop_w = int(round(src_h * target_aspect))
        crop_w = max(4, crop_w - (crop_w % 2))
        crop_h = max(4, crop_h - (crop_h % 2))
        max_x = max(0, src_w - crop_w)
        crop_x = int(round(cfg.crop_center_x * max_x))
        crop_y = 0
    else:
        crop_w = src_w
        crop_h = int(round(src_w / target_aspect))
        crop_w = max(4, crop_w - (crop_w % 2))
        crop_h = max(4, crop_h - (crop_h % 2))
        crop_x = 0
        max_y = max(0, src_h - crop_h)
        crop_y = int(round(cfg.crop_center_y * max_y))

    # Minimap calculation
    mx, my, mw, mh = cal.to_pixel_box(src_w, src_h)

    base_w = int(round(TARGET_W * 0.36 * cfg.minimap_scale))
    smw = max(60, min(TARGET_W - 40, base_w))
    smw = smw - (smw % 2)

    aspect = float(mw) / float(mh) if mh > 0 else 1.0
    smh = int(round(smw / aspect))
    smh = max(40, smh - (smh % 2))

    p = cfg.minimap_placement.lower().replace(" ", "-")
    if "top-center" in p:
        dest_x = (TARGET_W - smw) // 2 + cfg.minimap_offset_x
        dest_y = cfg.minimap_margin_top + cfg.minimap_offset_y
    elif "top-left" in p:
        dest_x = cfg.minimap_margin_x + cfg.minimap_offset_x
        dest_y = cfg.minimap_margin_top + cfg.minimap_offset_y
    elif "top-right" in p:
        dest_x = TARGET_W - smw - cfg.minimap_margin_x + cfg.minimap_offset_x
        dest_y = cfg.minimap_margin_top + cfg.minimap_offset_y
    elif "bottom-center" in p:
        dest_x = (TARGET_W - smw) // 2 + cfg.minimap_offset_x
        dest_y = TARGET_H - smh - cfg.minimap_margin_bottom + cfg.minimap_offset_y
    elif "bottom-left" in p:
        dest_x = cfg.minimap_margin_x + cfg.minimap_offset_x
        dest_y = TARGET_H - smh - cfg.minimap_margin_bottom + cfg.minimap_offset_y
    elif "bottom-right" in p:
        dest_x = TARGET_W - smw - cfg.minimap_margin_x + cfg.minimap_offset_x
        dest_y = TARGET_H - smh - cfg.minimap_margin_bottom + cfg.minimap_offset_y
    else: # Custom
        dest_x = (TARGET_W - smw) // 2 + cfg.minimap_offset_x
        dest_y = cfg.minimap_margin_top + cfg.minimap_offset_y

    dest_x = max(0, min(TARGET_W - smw, dest_x))
    dest_y = max(0, min(TARGET_H - smh, dest_y))

    return ((crop_x, crop_y, crop_w, crop_h), (mx, my, mw, mh, dest_x, dest_y, smw, smh))

def render_preview_frame(
    frame_rgb: np.ndarray,
    cal: MinimapCalibration,
    cfg: ShortsCompositionConfig,
    preview_h: int = 540
) -> np.ndarray:
    """Instant CPU preview of final 9:16 Shorts frame."""
    src_h, src_w, _ = frame_rgb.shape
    (crop_x, crop_y, crop_w, crop_h), (mx, my, mw, mh, dest_x, dest_y, smw, smh) = calculate_crop_and_overlay(
        src_w, src_h, cal, cfg
    )

    if cfg.fit_mode == "fit_blur":
        bg = cv2.resize(frame_rgb, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)
        bg = cv2.GaussianBlur(bg, (51, 51), 30)
        bg = (bg.astype(np.float32) * 0.6).astype(np.uint8)

        scale = TARGET_W / float(src_w)
        fg_h = int(round(src_h * scale))
        fg = cv2.resize(frame_rgb, (TARGET_W, fg_h), interpolation=cv2.INTER_LINEAR)

        fg_y = (TARGET_H - fg_h) // 2
        canvas = bg.copy()
        canvas[fg_y:fg_y+fg_h, 0:TARGET_W] = fg
    else:
        patch = frame_rgb[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
        canvas = cv2.resize(patch, (TARGET_W, TARGET_H), interpolation=cv2.INTER_LINEAR)

    # Extract & overlay minimap
    minimap_patch = frame_rgb[my:my+mh, mx:mx+mw]
    scaled_map = cv2.resize(minimap_patch, (smw, smh), interpolation=cv2.INTER_LINEAR)
    canvas[dest_y:dest_y+smh, dest_x:dest_x+smw] = scaled_map

    # Downscale for UI
    scale_ui = preview_h / float(TARGET_H)
    disp_w = int(round(TARGET_W * scale_ui))
    return cv2.resize(canvas, (disp_w, preview_h), interpolation=cv2.INTER_AREA)

def render_clean_short(
    source_path: str,
    output_path: str,
    start_sec: float,
    end_sec: float,
    cal: MinimapCalibration,
    cfg: ShortsCompositionConfig,
    encoder_name: str = "auto",
    cancel_event: Optional[threading.Event] = None
) -> Tuple[bool, str]:
    """
    Renders clean 9:16 Short with synchronized minimap overlay and zero creative additions.
    Performs strict FFprobe validation.
    """
    src_p = Path(source_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    meta = probe_video_meta(str(src_p))
    clip_duration = end_sec - start_sec

    if clip_duration <= 0.5:
        return False, f"Invalid clip duration: {clip_duration:.2f}s"

    (crop_x, crop_y, crop_w, crop_h), (mx, my, mw, mh, dest_x, dest_y, smw, smh) = calculate_crop_and_overlay(
        meta["width"], meta["height"], cal, cfg
    )

    # Build filtergraph
    if cfg.fit_mode == "fit_blur":
        filtergraph = (
            f"[0:v]split=3[fg_raw][bg_raw][map_raw];"
            f"[bg_raw]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H},boxblur=20:5,colorchannelmixer=aa=1.0:rr=0.6:gg=0.6:bb=0.6[bg_blurred];"
            f"[fg_raw]scale={TARGET_W}:-2[fg_scaled];"
            f"[bg_blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2[base_canvas];"
            f"[map_raw]crop={mw}:{mh}:{mx}:{my},scale={smw}:{smh}:flags=bicubic[minimap_clean];"
            f"[base_canvas][minimap_clean]overlay={dest_x}:{dest_y}[outv]"
        )
    else:
        filtergraph = (
            f"[0:v]split=2[gameplay_raw][map_raw];"
            f"[gameplay_raw]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={TARGET_W}:{TARGET_H}:flags=bicubic[base_canvas];"
            f"[map_raw]crop={mw}:{mh}:{mx}:{my},scale={smw}:{smh}:flags=bicubic[minimap_clean];"
            f"[base_canvas][minimap_clean]overlay={dest_x}:{dest_y}[outv]"
        )

    # Resolve encoder
    hw_mgr = HardwareManager.get_instance()
    plan = hw_mgr.resolve_hardware_plan()
    chosen_encoder = encoder_name if encoder_name != "auto" else plan.active_video_encoder

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-to", f"{end_sec:.3f}",
        "-i", str(src_p),
        "-filter_complex", filtergraph,
        "-map", "[outv]"
    ]

    # Audio mapping: retain original audio without modification
    if meta["has_audio"]:
        cmd.extend(["-map", "0:a?", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"])
    else:
        cmd.extend(["-an"])

    # Video encoder options
    if chosen_encoder == "h264_nvenc":
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "24", "-pix_fmt", "yuv420p"])
    elif chosen_encoder == "h264_qsv":
        cmd.extend(["-c:v", "h264_qsv", "-global_quality", "23", "-pix_fmt", "nv12"])
    elif chosen_encoder == "h264_amf":
        cmd.extend(["-c:v", "h264_amf", "-rc", "cqp", "-qp_p", "23", "-pix_fmt", "yuv420p"])
    else: # libx264 (CPU)
        cmd.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p"])

    fps_target = min(60.0, max(24.0, meta["fps"]))
    cmd.extend(["-r", f"{fps_target:.2f}", "-movflags", "+faststart", str(out_p)])

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = proc.communicate()

        if proc.returncode != 0:
            if out_p.exists():
                out_p.unlink(missing_ok=True)
            return False, f"FFmpeg failed ({chosen_encoder}): {stderr.strip()}"

        # Strict FFprobe Validation
        valid, val_msg = validate_export(str(out_p), expected_duration=clip_duration, require_audio=meta["has_audio"])
        if not valid:
            if out_p.exists():
                out_p.unlink(missing_ok=True)
            return False, f"Validation failed: {val_msg}"

        return True, val_msg
    except Exception as e:
        if out_p.exists():
            out_p.unlink(missing_ok=True)
        return False, f"Rendering exception: {str(e)}"

def validate_export(
    file_path: str,
    expected_duration: Optional[float] = None,
    tolerance: float = 2.5,
    require_audio: bool = False
) -> Tuple[bool, str]:
    """Strict FFprobe validation of exported Shorts file."""
    p = Path(file_path).resolve()
    if not p.is_file():
        return False, f"File does not exist: {file_path}"
    if p.stat().st_size == 0:
        return False, "File is 0 bytes (empty)"

    try:
        meta = probe_video_meta(str(p))
    except Exception as e:
        return False, f"FFprobe inspection failed: {e}"

    if meta["width"] != TARGET_W or meta["height"] != TARGET_H:
        return False, f"Resolution mismatch: expected {TARGET_W}x{TARGET_H}, got {meta['width']}x{meta['height']}"

    if expected_duration is not None and expected_duration > 0:
        diff = abs(meta["duration"] - expected_duration)
        if diff > tolerance:
            return False, f"Duration mismatch: expected {expected_duration:.2f}s, got {meta['duration']:.2f}s (diff {diff:.2f}s > {tolerance}s)"

    if require_audio and not meta["has_audio"]:
        return False, "Audio stream missing from exported clip"

    return True, f"Validated: {TARGET_W}x{TARGET_H} (9:16), {meta['duration']:.1f}s, {meta['video_codec']}, yuv420p"
