# THIRD-PARTY NOTICES & OPEN-SOURCE ATTRIBUTIONS

LEONIDEX is built on open-source software and established community foundations. This document records all upstream codebases, licenses, inspection references, and architectural adaptations made to create LEONIDEX.

---

## 1. Primary Base Repository

* **Repository:** `utkualsir/sharkyclips`
* **Upstream URL:** [https://github.com/utkualsir/sharkyclips](https://github.com/utkualsir/sharkyclips)
* **Analyzed & Pinned Version:** 1.2.50
* **Pinned Commit Hash:** `cf7a5a007e44d8c1316e0fccd465d820262ee746`
* **License:** MIT License
* **Copyright:** (c) 2024 Utku Alsir

### Role in LEONIDEX:
`utkualsir/sharkyclips` provides the primary core foundation for LEONIDEX:
- React 18 frontend with TypeScript and Vite.
- FastAPI backend server with job queuing and background workers.
- Hardware detection (CPU cores, RAM, GPU, CUDA status) and FFmpeg encoder test probing.
- Local media processing pipeline with FFmpeg and OpenCV.
- faster-whisper transcription engine integration.

### What Was Kept, Adapted, or Replaced:
1. **Kept:**
   - React 18 + Vite frontend build infrastructure and dark/light UI design tokens.
   - FastAPI application lifecycle, WebSockets/SSE job streaming, and governor process monitor.
   - Core FFmpeg subprocess invocation utilities (`sharkyclips.procs`, `sharkyclips.hardware`).
   - faster-whisper model management and device mapping.
2. **Replaced:**
   - **Subtitle & Creative Effects Pipeline:** SharkyClips upstream defaults to burning in animated captions, hook headers, voiceovers, stickers, and split-screen facecam. In LEONIDEX, this entire creative layer is replaced by `sharkyclips.render_shorts` (`render_clean_short`), which strictly enforces **zero creative additions** (no subtitles, captions, hook text, sound effects, or decorative frames).
   - **Ingestion Scope:** Upstream URL downloading (YouTube, Twitch, Kick), social auto-posting, and cloud sync are bypassed in favor of local-only file ingestion via `/api/video/open-dialog` and `/api/video/load`.
   - **Persistence Layer:** Upstream relies on scattered project JSON files. LEONIDEX introduces canonical SQLite database persistence (`sharkyclips.db.database`) for video sessions, candidates, minimap calibration profiles, and export verification jobs.
3. **Added:**
   - **HUD Minimap Calibration Engine (`sharkyclips.minimap`):** Frame-level HUD extraction, normalized bounding boxes, presets (GTA V, GTA IV), auto-detect heuristic, and synchronized overlay rendering.
   - **GTA Multi-Signal Highlight Detector (`sharkyclips.highlights.gta`):** Multi-signal fusion combining audio volume/energy surges with visual frame-difference motion and flash deltas (sampled at 1 fps, 320x180) to reliably locate action sequences.
   - **Dual-Execution Hardware Manager (`sharkyclips.hardware_selector`):** Explicit runtime separation between Whisper inference device (`auto`/`cpu`/`cuda`) and FFmpeg hardware video encoder (`libx264`/`h264_nvenc`/`h264_qsv`/`h264_amf`), with graceful CPU fallback and telemetry warnings.
   - **Dedicated LEONIDEX Studio UI (`frontend/src/pages/Leonidex.tsx`):** All-in-one control panel featuring real-time hardware telemetry, video player, highlight candidate table with In/Out fine-tuning, interactive calibration canvas, live 9:16 preview, and batch export queue with automated FFprobe validation.

---

## 2. Secondary Technical References Inspected

The following repositories were examined as technical references for architectural patterns, domain logic, and validation strategies:

### A. AI YouTube Shorts Generator
* **Repository:** `Anil-matcha/AI-Youtube-Shorts-Generator`
* **URL:** [https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator)
* **License:** MIT License
* **Attributed Concepts:** Overlapping analysis windows, highlight deduplication heuristics, vertical 9:16 cropping geometry.
* **Deviations:** Discarded proprietary cloud dependencies (MuAPI, OpenAI API); LEONIDEX executes entirely locally.

### B. PeakCut
* **Repository:** `haziqahmedqasmi/peakcut`
* **URL:** [https://github.com/haziqahmedqasmi/peakcut](https://github.com/haziqahmedqasmi/peakcut)
* **License:** MIT License
* **Attributed Concepts:** FastAPI application structure, SQLite database models, gaming highlight scoring concepts.
* **Deviations:** PeakCut's `GAMING.md` gaming mode was determined to be prompt-based text analysis rather than actual computer vision. LEONIDEX implements true computer vision on video frames.

### C. Auto-Clipper
* **Repository:** `bendawg2010/Auto-clipper`
* **URL:** [https://github.com/bendawg2010/Auto-clipper](https://github.com/bendawg2010/Auto-clipper)
* **License:** MIT License
* **Attributed Concepts:** Motion delta calculation, audio spike thresholding, per-game profile calibration concepts.
* **Deviations:** Auto-Clipper's existing pre-trained weights for Arc Raiders and War Thunder were not ported; instead, an authentic GTA-tailored detection pipeline was engineered.

### D. ClipForge
* **Repository:** `Avilash2001/ClipForge`
* **URL:** [https://github.com/Avilash2001/ClipForge](https://github.com/Avilash2001/ClipForge)
* **License:** MIT License
* **Attributed Concepts:** CUDA 12 and cuDNN library detection, float16 -> int8 -> CPU out-of-memory fallback sequence, candidate boundary verification.
* **Deviations:** Avoided making heavyweight Ollama vision models mandatory so LEONIDEX runs reliably on both GPU workstations and CPU-only servers.

---

## 3. MIT License Text (Primary Upstream)

```
MIT License

Copyright (c) 2024 Utku Alsir

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
