"""
LEONIDEX — Web Application Launcher
Runs FastAPI backend with React frontend and SQLite database.

Base application: utkualsir/sharkyclips (MIT)
Adapted for LEONIDEX Local Highlight Detection & Clean 9:16 Shorts Generation.
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# Ensure backend directory is in python path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def free_port_if_occupied(port: int):
    if not is_port_in_use(port):
        return
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
            for line in out.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    pid = int(line.strip().split()[-1])
                    if pid > 0 and pid != os.getpid():
                        print(f"  [Port {port}] Releasing occupied socket (closing PID {pid})...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                        time.sleep(0.6)
        except Exception:
            pass

def find_available_port(start_port: int = 8000, host: str = "127.0.0.1") -> int:
    free_port_if_occupied(start_port)
    if not is_port_in_use(start_port, host):
        return start_port
    # If still occupied, find next open port
    for p in range(start_port + 1, start_port + 20):
        if not is_port_in_use(p, host):
            return p
    return start_port

def main(host: str = "127.0.0.1", requested_port: int = 8000, open_browser: bool = True):
    port = find_available_port(requested_port, host)
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
        def launch_tab():
            time.sleep(1.0)
            try:
                webbrowser.open(f"{url}/#/leonidex")
            except Exception:
                pass
        import threading
        t = threading.Thread(target=launch_tab, daemon=True)
        t.start()

    uvicorn.run("sharkyclips.web.app:app", host=host, port=port, reload=False, log_level="info")

if __name__ == "__main__":
    p = 8000
    for idx, arg in enumerate(sys.argv):
        if arg in ("--port", "-p") and idx + 1 < len(sys.argv):
            p = int(sys.argv[idx + 1])
    main(requested_port=p)
