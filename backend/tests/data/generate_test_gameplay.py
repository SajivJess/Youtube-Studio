"""
Synthetic GTA Gameplay Video Generator for Realistic Testing
Generates a 1920x1080 30fps gameplay video with:
- Simulated driving scene and action bursts
- Bottom-left GTA HUD with animated circular minimap and player blip
- Synchronized multi-channel audio (engine hum, tire screech, crash boom, gunshots)
- Also generates a 1280x720 video with no audio stream for edge-case testing.
"""
import math
import os
import subprocess
import wave
from pathlib import Path
import numpy as np
import cv2

TESTS_DIR = Path(__file__).resolve().parent
TESTS_DIR.mkdir(parents=True, exist_ok=True)

def generate_gta_gameplay_video(
    output_path: Path,
    duration_sec: float = 45.0,
    fps: int = 30,
    width: int = 1920,
    height: int = 1080
):
    print(f"Generating realistic GTA gameplay video: {output_path.name} ({duration_sec}s, {width}x{height} @ {fps}fps)...")
    total_frames = int(duration_sec * fps)
    
    # 1. Synthesize audio track (16kHz mono, then mix into final video)
    audio_sr = 16000
    total_audio_samples = int(duration_sec * audio_sr)
    audio_t = np.linspace(0, duration_sec, total_audio_samples, endpoint=False)
    audio_signal = np.zeros(total_audio_samples, dtype=np.float32)

    # Ambient low engine hum (40Hz - 80Hz)
    audio_signal += 0.10 * np.sin(2 * np.pi * 55 * audio_t)

    # Event 1: Car Crash & Explosion at t=18s to 24s
    crash_start = int(18.0 * audio_sr)
    crash_end = int(24.0 * audio_sr)
    crash_len = crash_end - crash_start
    t_c = np.linspace(0, 6.0, crash_len)
    # Loud screech (2kHz) decaying into low explosion boom (60Hz rumble + noise)
    screech = 0.65 * np.sin(2 * np.pi * 1800 * t_c[:int(1.5 * audio_sr)]) * np.exp(-t_c[:int(1.5 * audio_sr)])
    boom = 0.85 * np.sin(2 * np.pi * 65 * t_c) * np.exp(-0.8 * t_c)
    noise = 0.40 * np.random.normal(0, 1, crash_len) * np.exp(-0.7 * t_c)
    audio_signal[crash_start:crash_start + len(screech)] += screech
    audio_signal[crash_start:crash_end] += (boom + noise).astype(np.float32)

    # Event 2: Rapid Gunshots & Siren at t=32s to 38s
    gun_start = int(32.0 * audio_sr)
    for shot_t in [32.2, 32.7, 33.1, 33.5, 34.0, 34.6, 35.2]:
        s_idx = int(shot_t * audio_sr)
        shot_len = int(0.25 * audio_sr)
        shot_env = np.exp(-np.linspace(0, 15, shot_len))
        shot_sound = 0.90 * np.random.normal(0, 1, shot_len) * shot_env
        audio_signal[s_idx:s_idx + shot_len] += shot_sound.astype(np.float32)

    # Police siren (700Hz - 1100Hz modulation) from t=22s to 42s
    siren_start = int(22.0 * audio_sr)
    siren_end = int(42.0 * audio_sr)
    siren_len = siren_end - siren_start
    t_s = np.linspace(0, 20.0, siren_len)
    siren_freq = 850 + 250 * np.sin(2 * np.pi * 0.5 * t_s)
    siren = 0.25 * np.sin(2 * np.pi * siren_freq * t_s)
    audio_signal[siren_start:siren_end] += siren.astype(np.float32)

    # Normalize audio
    audio_signal = np.clip(audio_signal, -0.98, 0.98)
    audio_i16 = (audio_signal * 32767).astype(np.int16)

    temp_wav = TESTS_DIR / "temp_synth_audio.wav"
    with wave.open(str(temp_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(audio_sr)
        wf.writeframes(audio_i16.tobytes())

    # 2. Render video frames into FFmpeg pipe
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(temp_wav),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path)
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    # Minimap constants (Bottom-left GTA HUD)
    # x=0.024*1920 = 46, y=0.755*1080 = 815, w=316, h=226
    hud_x = int(0.024 * width)
    hud_y = int(0.755 * height)
    hud_w = int(0.165 * width)
    hud_h = int(0.210 * height)
    map_cx = hud_x + hud_w // 2
    map_cy = hud_y + int(hud_h * 0.42)
    map_radius = int(hud_h * 0.38)

    for f_idx in range(total_frames):
        t = f_idx / fps
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Background gameplay scene (Sky + Horizon + Moving asphalt road)
        # Event states:
        is_crash = 18.0 <= t <= 24.0
        is_shootout = 32.0 <= t <= 38.0

        if is_crash:
            # Flashing orange/red fire & dust
            flash = math.sin(t * 15.0) * 0.5 + 0.5
            sky_color = [int(30 + 100 * flash), int(50 + 60 * flash), int(160 + 90 * flash)]
        elif is_shootout:
            # Muzzle flash bursts
            muzzle = 1.0 if (int(t * 10) % 3 == 0) else 0.0
            sky_color = [int(120 + 80 * muzzle), int(100 + 80 * muzzle), int(90 + 80 * muzzle)]
        else:
            # Sunny Los Santos sky
            sky_color = [230, 180, 100]

        horizon_y = int(height * 0.45)
        frame[0:horizon_y, :] = sky_color  # Sky

        # Distant city buildings
        for b_i in range(12):
            bx = b_i * 170 + 40
            bw = 110
            bh = 120 + (b_i * 37) % 180
            by = horizon_y - bh
            cv2.rectangle(frame, (bx, by), (bx + bw, horizon_y), (80 + (b_i * 10) % 40, 75, 70), -1)

        # Ground / Asphalt
        frame[horizon_y:, :] = [45, 45, 45]

        # Moving road lane markings (perspective lines)
        road_speed = 400.0 if not is_crash else 50.0
        dash_offset = int((t * road_speed) % 120)
        for dy in range(horizon_y, height, 60):
            y_pos = dy + dash_offset
            if y_pos < height:
                scale_y = (y_pos - horizon_y) / (height - horizon_y)
                lane_w = max(4, int(18 * scale_y))
                cv2.rectangle(frame, (width // 2 - lane_w // 2, y_pos), (width // 2 + lane_w // 2, y_pos + int(35 * scale_y)), (200, 220, 240), -1)

        # Player vehicle in 3rd person center view
        car_y = int(height * 0.68)
        car_w = int(240 * (width / 1920.0))
        car_h = int(120 * (height / 1080.0))
        car_x = (width - car_w) // 2

        if is_crash:
            # Car wobbles/spins
            car_x += int(40 * math.sin(t * 12))

        # Draw sports car
        cv2.rectangle(frame, (car_x, car_y + car_h // 3), (car_x + car_w, car_y + car_h), (25, 25, 200), -1) # Red body
        cv2.rectangle(frame, (car_x + 30, car_y), (car_x + car_w - 30, car_y + car_h // 3), (40, 40, 40), -1) # Roof/windshield
        # Tail lights
        cv2.circle(frame, (car_x + 20, car_y + car_h - 20), 10, (0, 0, 255), -1)
        cv2.circle(frame, (car_x + car_w - 20, car_y + car_h - 20), 10, (0, 0, 255), -1)

        # Explosion VFX during crash
        if is_crash:
            c_rel = t - 18.0
            exp_radius = int(min(220, c_rel * 70))
            cv2.circle(frame, (car_x + car_w // 2, car_y), exp_radius, (0, 140, 255), -1)
            cv2.circle(frame, (car_x + car_w // 2, car_y), int(exp_radius * 0.6), (0, 230, 255), -1)

        # ==========================================
        # AUTHENTIC GTA HUD & MINIMAP (BOTTOM-LEFT)
        # ==========================================
        # 1. Dark HUD backing
        cv2.rectangle(frame, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (20, 20, 20), -1)
        cv2.rectangle(frame, (hud_x, hud_y), (hud_x + hud_w, hud_y + hud_h), (60, 60, 60), 2)

        # 2. Circular Radar Minimap
        cv2.circle(frame, (map_cx, map_cy), map_radius, (50, 45, 40), -1)
        cv2.circle(frame, (map_cx, map_cy), map_radius, (200, 200, 200), 3)

        # Moving roads inside minimap
        road_angle = t * 0.8  # vehicle heading rotation
        cos_a = math.cos(road_angle)
        sin_a = math.sin(road_angle)
        
        # Draw 2 intersecting simulated streets inside radar
        p1 = (int(map_cx - map_radius * 0.9 * cos_a), int(map_cy - map_radius * 0.9 * sin_a))
        p2 = (int(map_cx + map_radius * 0.9 * cos_a), int(map_cy + map_radius * 0.9 * sin_a))
        cv2.line(frame, p1, p2, (140, 140, 140), 6)

        p3 = (int(map_cx - map_radius * 0.9 * (-sin_a)), int(map_cy - map_radius * 0.9 * cos_a))
        p4 = (int(map_cx + map_radius * 0.9 * (-sin_a)), int(map_cy + map_radius * 0.9 * cos_a))
        cv2.line(frame, p3, p4, (120, 120, 120), 4)

        # Center player blip (white triangle pointing up)
        tri_pts = np.array([
            [map_cx, map_cy - 12],
            [map_cx - 9, map_cy + 10],
            [map_cx + 9, map_cy + 10]
        ], np.int32)
        cv2.fillPoly(frame, [tri_pts], (255, 255, 255))
        cv2.polylines(frame, [tri_pts], True, (0, 0, 0), 2)

        # Objective / mission marker blip (yellow dot)
        obj_x = int(map_cx + map_radius * 0.55 * math.sin(t * 0.4))
        obj_y = int(map_cy + map_radius * 0.55 * math.cos(t * 0.4))
        cv2.circle(frame, (obj_x, obj_y), 6, (0, 240, 255), -1)

        # Police wanted stars if in chase
        if is_crash or is_shootout:
            star_flash = (int(t * 4) % 2 == 0)
            star_color = (0, 220, 255) if star_flash else (60, 60, 60)
            cv2.putText(frame, "* * * *", (hud_x + 15, hud_y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, star_color, 2)

        # 3. Health (Green) & Armor (Blue) bars under radar
        bar_y1 = hud_y + int(hud_h * 0.84)
        bar_y2 = hud_y + int(hud_h * 0.92)
        bar_w = int(hud_w * 0.84)
        bar_start_x = hud_x + (hud_w - bar_w) // 2

        # Health bar (green)
        half_w = bar_w // 2 - 3
        cv2.rectangle(frame, (bar_start_x, bar_y1), (bar_start_x + half_w, bar_y1 + 6), (0, 180, 0), -1)
        # Armor bar (blue)
        cv2.rectangle(frame, (bar_start_x + half_w + 6, bar_y1), (bar_start_x + bar_w, bar_y1 + 6), (220, 120, 30), -1)

        # Send raw frame to ffmpeg
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    proc.wait()

    if temp_wav.exists():
        temp_wav.unlink(missing_ok=True)
    print(f"GTA gameplay video successfully created: {output_path} ({output_path.stat().st_size / (1024*1024):.1f} MB)")

def generate_no_audio_video(
    output_path: Path,
    duration_sec: float = 15.0,
    fps: int = 24,
    width: int = 1280,
    height: int = 720
):
    print(f"Generating video without audio stream: {output_path.name} ({duration_sec}s, {width}x{height})...")
    total_frames = int(duration_sec * fps)
    
    cmd = [
        "ffmpeg",
        "-v", "error",
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path)
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    for i in range(total_frames):
        t = i / fps
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Simple moving pattern
        cv2.rectangle(frame, (0, 0), (width, height), (int(t * 10) % 255, 100, 150), -1)
        cv2.circle(frame, (int((t * 100) % width), height // 2), 60, (255, 255, 255), -1)
        cv2.putText(frame, f"NO AUDIO TEST {t:.1f}s", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    proc.wait()
    print(f"No-audio video created: {output_path} ({output_path.stat().st_size / (1024*1024):.1f} MB)")

if __name__ == "__main__":
    gta_out = TESTS_DIR / "sample_gta_gameplay.mp4"
    generate_gta_gameplay_video(gta_out, duration_sec=45.0)

    no_audio_out = TESTS_DIR / "sample_no_audio_720p.mp4"
    generate_no_audio_video(no_audio_out, duration_sec=15.0)
