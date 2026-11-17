# LEONIDEX — Local Gameplay Highlight Detection & 9:16 Shorts Generator

**LEONIDEX** is a local, privacy-focused application for Windows and Linux that analyzes recorded gameplay footage, detects high-action highlight moments via multi-signal audio-visual fusion, synchronizes authentic HUD minimap crops, and exports clean 1080×1920 (9:16) vertical Shorts ready for final video editing.

Built on the open-source foundation of **`utkualsir/sharkyclips`** (MIT License, v1.2.50, commit `cf7a5a007e44d8c1316e0fccd465d820262ee746`).

---

## Key Features & Strict Scope Boundaries

1. **Local Media Processing Only:**
   - Ingests common local video formats: MP4, MKV, MOV, AVI, WEBM.
   - Zero URL downloading, YouTube/Twitch scraping, livestream monitoring, or cloud processing. Everything executes strictly on your local PC.
2. **Authentic HUD Minimap Overlay:**
   - Separately crops the in-game minimap directly from the source video frame.
   - Built-in presets for **GTA V Standard**, **GTA V Expanded Radar**, and **GTA IV Standard**.
   - Interactive calibration canvas with normalized coordinate controls ($X, Y, W, H$) and auto-detection heuristic.
   - Synchronized PIP placement (`Top-Center`, `Top-Left`, `Top-Right`, `Bottom-Center`) with customizable scaling.
3. **Multi-Signal GTA Highlight Detection:**
   - **Audio Analysis:** Analyzes source audio for energy surges, volume peaks, shouting, explosions, and high-impact sound events.
   - **Visual Motion & Flash Analysis:** Fast, low-overhead OpenCV frame sampling at 1 fps (320×180) to detect scene transitions, high-speed camera action, explosions, and vehicle collisions.
   - **Multi-Signal Fusion & Deduplication:** Combines audio peaks and visual motion bursts with context framing (3-5s pre-action context, 3-7s post-action aftermath) and non-maximum suppression deduplication.
4. **Strictly Clean 9:16 Export:**
   - **Zero Creative Additions:** No burned-in subtitles, animated captions, background music, sound effects, voiceovers, stickers, channel logos, or decorative frames.
   - The output is strictly clean gameplay footage + original game audio + synchronized HUD minimap.
5. **Dual-Execution Hardware Architecture:**
   - Dynamic runtime separation between **Whisper inference device** (`auto`, `cpu`, `cuda`) and **FFmpeg video encoder** (`auto`, `libx264`, `h264_nvenc`, `h264_qsv`, `h264_amf`).
   - Automatically probes hardware capabilities and gracefully falls back to CPU mode without crashing on GPU-free workstations or machines without CUDA DLLs.
6. **Canonical SQLite Storage:**
   - Full persistence for video sessions, highlight candidates, user timestamp adjustments, minimap calibration profiles, and export verification logs stored in `workspace/data/leonidex.db`.
7. **Automated FFprobe Verification:**
   - Every exported clip is automatically verified with FFprobe to ensure valid MP4 container, exact 1080×1920 resolution, 9:16 aspect ratio, yuv420p pixel format, H.264 video, and AAC audio.

---

## Tech Stack

* **Frontend:** React 18, TypeScript, Vite, CSS Design Tokens
* **Backend:** FastAPI, Python 3.12, Uvicorn, SQLAlchemy
* **Database:** SQLite (`workspace/data/leonidex.db`)
* **Computer Vision & Media:** OpenCV (Headless), FFmpeg, FFprobe, NumPy, SciPy
* **Speech / Audio:** faster-whisper (CTranslate2) with dynamic CUDA/CPU fallback

---

## Quick Start (Windows)

### 1. Prerequisites
- Python 3.11 or 3.12 installed and added to PATH.
- FFmpeg and FFprobe installed and available in system PATH.
- Node.js 18+ (only required if modifying and rebuilding the frontend).

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Launch the Application
To start both the FastAPI backend and serve the compiled React 18 UI:
```powershell
python main.py
```
Or directly:
```powershell
python run_server.py
```
This will automatically launch your default browser at:
`http://localhost:8000/#/leonidex`

---

## Application Architecture

```
YT CLIP/
├── backend/
│   ├── cli.py                        # Command-line administrative interface
│   ├── requirements.txt              # Core backend dependencies
│   ├── sharkyclips/
│   │   ├── config.py                 # Paths, workspace directories, global config
│   │   ├── hardware.py               # Hardware detection (CPU, RAM, GPU, CUDA)
│   │   ├── hardware_selector.py      # LEONIDEX Dual-execution Hardware Manager
│   │   ├── minimap.py                # HUD minimap extraction & calibration engine
│   │   ├── render_shorts.py          # Clean 9:16 Shorts renderer & FFprobe validator
│   │   ├── db/
│   │   │   ├── database.py           # SQLite connection & session generator
│   │   │   └── models.py             # SQLAlchemy models (Sessions, Candidates, Profiles)
│   │   ├── highlights/
│   │   │   └── gta.py                # Multi-signal GTA highlight detector
│   │   └── web/
│   │       ├── app.py                # FastAPI main application
│   │       └── leonidex_api.py       # REST API endpoints for LEONIDEX
│   └── tests/
│       ├── data/                     # Sample GTA gameplay videos for automated testing
│       └── test_leonidex_production.py # Comprehensive 19-test automated test suite
├── frontend/
│   ├── dist/                         # Compiled production bundle
│   └── src/
│       ├── App.tsx                   # Top-level app router and shell
│       ├── router.ts                 # Hash router configuration
│       └── pages/
│           └── Leonidex.tsx          # Dedicated LEONIDEX Studio control panel
├── workspace/                        # Runtime database and generated outputs
│   ├── data/leonidex.db              # Canonical SQLite database
│   └── outputs/                      # Exported clean vertical Shorts (1080x1920)
├── main.py                           # Application entry point
├── run_server.py                     # Uvicorn web server launcher
├── THIRD_PARTY_NOTICES.md            # Upstream MIT licenses and attribution
└── README.md                         # Documentation
```

---

## Workflow Guide

1. **Hardware Configuration:**
   - The top banner displays your host CPU cores, RAM, GPU model, and CUDA status.
   - Adjust the Whisper device (`Auto`, `CPU`, `CUDA`) and Video Encoder (`Auto`, `NVENC`, `libx264`, `QSV`, `AMF`) as needed.
2. **Video Ingestion:**
   - Click **Browse Video File...** to open the native OS file picker and select a local gameplay recording (MP4, MKV, MOV, AVI, WEBM).
   - Video metadata (duration, resolution, frame rate, codecs, file size) is probed and displayed, and the video loads in the HTML5 player.
3. **Highlight Detection:**
   - Click **Run Highlight Detection**.
   - The system scans the audio for volume spikes/explosions and the video frames for motion/flash changes.
   - Candidate moments appear in the interactive table with scores, rationales, and timestamps.
4. **Candidate Review & Trim:**
   - Use the **-1s** and **+1s** buttons to fine-tune clip start and end boundaries.
   - Click **Seek** to preview the moment in the video player.
   - Select or deselect clips using checkboxes or bulk buttons.
5. **Minimap Calibration:**
   - Choose a preset (e.g. `GTA V Standard`) or click **Auto-Detect HUD**.
   - Fine-tune the bounding box ($X, Y, W, H$) sliders and inspect the live crop preview.
   - Save custom presets for your resolution.
6. **9:16 Composition:**
   - Adjust horizontal framing ($0.15$ to $0.85$, default center $0.50$).
   - Choose vertical fit mode (`Crop` for full fill or `Blurred Background`).
   - Select minimap overlay placement (`Top-Center`, `Top-Left`, etc.) and scale.
   - View the live 9:16 preview.
7. **Clean Export & FFprobe Validation:**
   - Click **Export Selected Shorts**.
   - The backend renders vertical clips with your selected encoder.
   - Each completed clip is automatically validated with FFprobe.
   - Click **Watch Short** to preview the clean exported 9:16 MP4 Short.

---

## Automated Test Suite

To run the complete production test suite:
```powershell
cd backend
python -m pytest tests/test_leonidex_production.py -v
```

The test suite validates:
1. SQLite database initialization, table creation, and preset seeding.
2. Video and session record persistence and candidate updates.
3. Hardware Manager probe, plan resolution, and CPU fallback.
4. FFprobe metadata extraction on valid video and audio-less video.
5. Minimap frame extraction, normalized cropping, and auto-detection.
6. Multi-signal GTA highlight detection with audio and visual-only fallback.
7. 9:16 preview frame rendering and clean Shorts export with FFprobe verification.
8. Full FastAPI REST API endpoint contract.

---

## Attribution & License

LEONIDEX incorporates code from **`utkualsir/sharkyclips`** (MIT License, Copyright 2024 Utku Alsir).
See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for full licensing details and technical reference attributions.
