"""
LEONIDEX — Web Application Launcher
Runs FastAPI backend with React frontend and SQLite database.

Base application: utkualsir/sharkyclips (MIT)
Adapted for LEONIDEX Local Highlight Detection & Clean 9:16 Shorts Generation.
"""
import sys
import webbrowser
from pathlib import Path

# Ensure backend directory is in python path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn

def main(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True):
    url = f"http://{host}:{port}"

    print("\n" + "=" * 65)
    print("  🎮 LEONIDEX — Local Gameplay Highlight & 9:16 Shorts Generator")
    print("  Foundation: utkualsir/sharkyclips (v1.2.50, MIT)")
    print("  Tech Stack: React 18 (TypeScript) · FastAPI · SQLite · FFmpeg / OpenCV")
    print("=" * 65)
    print(f"  Backend & UI running on: {url}")
    print(f"  Direct LEONIDEX Studio:  {url}/#/leonidex")
    print("=" * 65 + "\n")

    if open_browser:
        try:
            webbrowser.open(f"{url}/#/leonidex")
        except Exception:
            pass

    uvicorn.run("sharkyclips.web.app:app", host=host, port=port, reload=False, log_level="info")

if __name__ == "__main__":
    p = 8000
    for idx, arg in enumerate(sys.argv):
        if arg in ("--port", "-p") and idx + 1 < len(sys.argv):
            p = int(sys.argv[idx + 1])
    main(port=p)
