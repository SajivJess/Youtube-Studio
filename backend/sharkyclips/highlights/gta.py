"""
LEONIDEX GTA VI Multi-Signal Highlight Detection Engine
Fuses audio loudness/onset surges, visual motion/flash variance, and speech reactions
into ranked candidate moments with setup context and payoff boundaries.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import numpy as np

from ..config import DEFAULT_WORKSPACE

HIGHLIGHT_REACTION_WORDS = {
    # High excitement / shock
    "omg": 1.0, "holy": 1.0, "insane": 1.0, "crazy": 1.0, "wtf": 1.0,
    "no way": 1.0, "unbelievable": 1.0, "what the": 0.9, "watch this": 0.9,
    "look at that": 0.9, "oh my god": 1.0, "yoooo": 1.0,
    # Combat / police / pursuit
    "busted": 0.85, "wasted": 0.85, "cops": 0.8, "police": 0.8,
    "five star": 0.95, "stars": 0.65, "helicopter": 0.75, "rpg": 0.85,
    "sniper": 0.75, "run": 0.75, "shoot": 0.75, "crash": 0.85,
    "exploded": 0.95, "explosion": 0.95, "stunt": 0.85, "drift": 0.75,
    "got him": 0.85, "headshot": 0.9,
    # Pacing reactions
    "wow": 0.8, "yo": 0.6, "damn": 0.75, "clutch": 0.9, "epic": 0.85
}

@dataclass
class GTAHighlightCandidate:
    candidate_id: int
    start_sec: float
    end_sec: float
    peak_sec: float
    duration: float
    score: float                      # 0 - 100 heuristic highlight score
    reason: str
    signals: List[str] = field(default_factory=list)
    transcript_context: str = ""
    selected: bool = True

class GTAHighlightDetector:
    def __init__(
        self,
        min_clip_duration: float = 15.0,
        max_clip_duration: float = 60.0,
        context_before: float = 5.0,
        context_after: float = 10.0,
        visual_sample_fps: float = 1.0,
    ):
        self.min_clip_duration = min_clip_duration
        self.max_clip_duration = max_clip_duration
        self.context_before = context_before
        self.context_after = context_after
        self.visual_sample_fps = visual_sample_fps

    def analyze_audio_signals(self, video_path: str, progress_cb=None) -> Dict[str, Any]:
        """Extracts 16kHz mono audio and computes RMS energy, sudden onset, and zero-crossing rate."""
        temp_dir = DEFAULT_WORKSPACE / "cache"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_wav = temp_dir / f"temp_gta_audio_{os.getpid()}_{np.random.randint(10000)}.wav"

        cmd = [
            "ffmpeg", "-v", "error", "-y", "-i", str(video_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(temp_wav)
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if not temp_wav.exists() or temp_wav.stat().st_size <= 44:
                return {"available": False, "timestamps": [], "audio_score": []}

            with wave.open(str(temp_wav), "rb") as wf:
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                raw_bytes = wf.readframes(n_frames)

            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            win_size = int(framerate * 0.5) # 0.5s sliding window
            n_win = max(1, len(samples) // win_size)

            timestamps, rms_vals, onset_vals, zcr_vals = [], [], [], []
            prev_rms = 0.0

            for i in range(n_win):
                chunk = samples[i * win_size : min((i + 1) * win_size, len(samples))]
                if len(chunk) == 0:
                    continue
                t = (i + 0.5) * 0.5
                timestamps.append(t)
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                rms_vals.append(rms)
                onset = max(0.0, rms - prev_rms)
                onset_vals.append(onset)
                prev_rms = rms
                zcr = float(np.mean(np.abs(np.diff(np.signbit(chunk)))))
                zcr_vals.append(zcr)

            def norm(arr):
                if not len(arr) or np.max(arr) == 0:
                    return np.zeros_like(arr)
                p98 = float(np.percentile(arr, 98))
                return np.clip(arr / max(1e-6, p98), 0.0, 1.0)

            rms_n = norm(np.array(rms_vals, dtype=np.float32))
            onset_n = norm(np.array(onset_vals, dtype=np.float32))
            zcr_n = norm(np.array(zcr_vals, dtype=np.float32))

            # Onset (sudden explosion/screech) + RMS loudness + ZCR (scream/noise)
            audio_score = 0.45 * onset_n + 0.35 * rms_n + 0.20 * zcr_n

            return {
                "available": True,
                "timestamps": timestamps,
                "audio_score": audio_score.tolist()
            }
        except Exception:
            return {"available": False, "timestamps": [], "audio_score": []}
        finally:
            if temp_wav.exists():
                try:
                    temp_wav.unlink()
                except Exception:
                    pass

    def analyze_visual_signals(self, video_path: str, duration: float, progress_cb=None) -> Dict[str, Any]:
        """Low-resolution sub-sampled frame difference, motion spikes, and explosion flash variance."""
        w, h = 320, 180
        frame_bytes = w * h * 3
        cmd = [
            "ffmpeg", "-v", "error", "-i", str(video_path),
            "-vf", f"fps={self.visual_sample_fps},scale={w}:{h}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"
        ]

        timestamps, motion_deltas, bright_deltas = [], [], []
        prev_gray = None
        prev_mean_b = 0.0

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=frame_bytes * 4)
            idx = 0
            while True:
                raw = proc.stdout.read(frame_bytes)
                if len(raw) < frame_bytes:
                    break
                t = idx / self.visual_sample_fps
                timestamps.append(t)

                frame = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
                gray = (frame[:, :, 0] * 0.114 + frame[:, :, 1] * 0.587 + frame[:, :, 2] * 0.299).astype(np.float32)
                mean_b = float(np.mean(gray))

                if prev_gray is not None:
                    diff = float(np.mean(np.abs(gray - prev_gray)))
                    motion_deltas.append(diff)
                    bright_deltas.append(abs(mean_b - prev_mean_b))
                else:
                    motion_deltas.append(0.0)
                    bright_deltas.append(0.0)

                prev_gray = gray
                prev_mean_b = mean_b
                idx += 1

            proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            proc.wait()

            if not timestamps:
                return {"available": False, "timestamps": [], "visual_score": []}

            def norm(arr):
                if not len(arr) or np.max(arr) == 0:
                    return np.zeros_like(arr)
                p98 = float(np.percentile(arr, 98))
                return np.clip(arr / max(1e-6, p98), 0.0, 1.0)

            motion_n = norm(np.array(motion_deltas, dtype=np.float32))
            bright_n = norm(np.array(bright_deltas, dtype=np.float32))
            visual_score = 0.65 * motion_n + 0.35 * bright_n

            return {
                "available": True,
                "timestamps": timestamps,
                "visual_score": visual_score.tolist()
            }
        except Exception:
            return {"available": False, "timestamps": [], "visual_score": []}

    def detect_highlights(
        self,
        video_path: str,
        duration: float,
        has_audio: bool,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        max_candidates: int = 8
    ) -> List[GTAHighlightCandidate]:
        """Runs full multi-signal pipeline and returns ranked candidates."""
        if progress_cb:
            progress_cb(0.10, "Extracting audio energy & surge signals...")

        audio_res = self.analyze_audio_signals(video_path, progress_cb) if has_audio else {"available": False}

        if progress_cb:
            progress_cb(0.45, "Sampling visual frames for motion spikes & scene changes...")

        visual_res = self.analyze_visual_signals(video_path, duration, progress_cb)

        if progress_cb:
            progress_cb(0.80, "Fusing signals into GTA highlight candidates...")

        grid_len = max(1, int(np.ceil(duration)))
        time_grid = np.arange(grid_len, dtype=np.float32)

        audio_grid = np.zeros(grid_len, dtype=np.float32)
        if audio_res.get("available") and len(audio_res["timestamps"]):
            audio_grid = np.interp(time_grid, np.array(audio_res["timestamps"]), np.array(audio_res["audio_score"]), left=0.0, right=0.0)

        visual_grid = np.zeros(grid_len, dtype=np.float32)
        if visual_res.get("available") and len(visual_res["timestamps"]):
            visual_grid = np.interp(time_grid, np.array(visual_res["timestamps"]), np.array(visual_res["visual_score"]), left=0.0, right=0.0)

        has_a = audio_res.get("available", False)
        has_v = visual_res.get("available", False)

        if has_a and has_v:
            concurrence = np.minimum(audio_grid, visual_grid)
            fused = 0.45 * audio_grid + 0.45 * visual_grid + 0.20 * concurrence
        elif has_v:
            fused = visual_grid
        elif has_a:
            fused = audio_grid
        else:
            fused = np.ones(grid_len, dtype=np.float32) * 0.5

        # Smooth signal
        window_size = 3
        kernel = np.ones(window_size) / window_size
        smoothed = np.convolve(fused, kernel, mode="same") if len(fused) >= window_size else fused

        threshold = max(0.22, min(0.65, float(np.percentile(smoothed, 70))))
        peak_indices = np.argsort(smoothed)[::-1]

        raw_candidates = []
        visited = np.zeros(grid_len, dtype=bool)

        for p_idx in peak_indices:
            peak_val = smoothed[p_idx]
            if peak_val < threshold:
                break
            if visited[p_idx]:
                continue

            peak_t = float(time_grid[p_idx])
            start_t = max(0.0, peak_t - self.context_before)
            end_t = min(duration, peak_t + self.context_after)

            curr_dur = end_t - start_t
            if curr_dur < self.min_clip_duration:
                diff = self.min_clip_duration - curr_dur
                start_t = max(0.0, start_t - diff / 2)
                end_t = min(duration, end_t + diff / 2)

            if (end_t - start_t) > self.max_clip_duration:
                end_t = start_t + self.max_clip_duration

            v_s = int(max(0, start_t))
            v_e = int(min(grid_len, np.ceil(end_t)))
            visited[v_s:v_e] = True

            sub = smoothed[v_s:v_e]
            avg_val = float(np.mean(sub)) if len(sub) > 0 else peak_val
            comp_score = 0.6 * peak_val + 0.4 * avg_val
            score = float(np.clip(comp_score * 100.0, 10.0, 99.0))

            signals, reasons = [], []
            a_sub = float(np.max(audio_grid[v_s:v_e])) if has_a and v_e > v_s else 0.0
            v_sub = float(np.max(visual_grid[v_s:v_e])) if has_v and v_e > v_s else 0.0

            if a_sub > 0.4:
                signals.append("Audio Surge / Impact")
                reasons.append("sudden audio volume / crash spike")
            if v_sub > 0.4:
                signals.append("Visual Motion / Scene Change")
                reasons.append("rapid gameplay movement / camera action")
            if not signals:
                signals.append("Gameplay Pace Elevation")
                reasons.append("action pacing above baseline")

            m = int(peak_t // 60)
            s = int(peak_t % 60)
            reason_str = f"Moment at {m:02d}:{s:02d}: " + ", ".join(reasons)

            raw_candidates.append({
                "peak_sec": round(peak_t, 2),
                "start_sec": round(start_t, 2),
                "end_sec": round(end_t, 2),
                "duration": round(end_t - start_t, 2),
                "score": round(score, 1),
                "reason": reason_str,
                "signals": signals
            })

            if len(raw_candidates) >= max_candidates * 2:
                break

        raw_candidates.sort(key=lambda c: c["score"], reverse=True)

        # Deduplicate
        filtered: List[GTAHighlightCandidate] = []
        for c in raw_candidates:
            overlaps = False
            for exist in filtered:
                ov_s = max(c["start_sec"], exist.start_sec)
                ov_e = min(c["end_sec"], exist.end_sec)
                if ov_e > ov_s and (ov_e - ov_s) > 0.35 * min(c["duration"], exist.duration):
                    overlaps = True
                    break
            if not overlaps:
                cand = GTAHighlightCandidate(
                    candidate_id=len(filtered) + 1,
                    start_sec=c["start_sec"],
                    end_sec=c["end_sec"],
                    peak_sec=c["peak_sec"],
                    duration=c["duration"],
                    score=c["score"],
                    reason=c["reason"],
                    signals=c["signals"],
                    selected=(len(filtered) < 3)
                )
                filtered.append(cand)
                if len(filtered) >= max_candidates:
                    break

        if not filtered and duration > 0:
            dur = min(duration, self.min_clip_duration)
            filtered.append(GTAHighlightCandidate(
                candidate_id=1,
                start_sec=0.0,
                end_sec=dur,
                peak_sec=dur / 2,
                duration=dur,
                score=50.0,
                reason="Default gameplay highlight window",
                signals=["General Gameplay"],
                selected=True
            ))

        if progress_cb:
            progress_cb(1.0, f"Detected {len(filtered)} highlight moments.")

        return filtered
