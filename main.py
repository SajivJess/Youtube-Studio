"""
LEONIDEX — Local Gameplay Highlight Detection & Shorts Generator
Primary Entry Point.

Foundation: utkualsir/sharkyclips (MIT, v1.2.50)
Tech Stack: React 18 · FastAPI · SQLite · FFmpeg / OpenCV

Usage:
    python main.py                  # Launches React + FastAPI Web Application (Default)
    python main.py --cli [args]     # Headless CLI for backend management
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        import cli
        sys.argv.pop(1)
        cli.main()
    else:
        from run_server import main as web_main
        web_main()

if __name__ == "__main__":
    main()
