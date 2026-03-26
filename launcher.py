#!/usr/bin/env python3
"""
STS Test Runner — launcher.

Cross-platform entry point:
  - Activates the .venv if it exists (when called from launcher.command / launcher.bat)
  - Checks that Flask is installed
  - Starts the Flask server on port 5678 (or the next free port)
  - Waits until the server is ready
  - Opens http://localhost:<port> in the default browser
  - Keeps running until Ctrl-C or the terminal is closed

Usage:
    python launcher.py              # any platform
    double-click launcher.command   # macOS Finder
    double-click launcher.bat       # Windows Explorer
"""
from __future__ import annotations

import importlib.util
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
UI_APP = PROJECT_ROOT / "ui" / "app.py"
DEFAULT_PORT = 5678


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_port(start: int = DEFAULT_PORT) -> int:
    port = start
    while not _port_free(port):
        print(f"Port {port} already in use, trying {port + 1}…")
        port += 1
    return port


def _wait_for_server(url: str, timeout: float = 20.0) -> bool:
    """Poll GET /status until the server responds or timeout expires."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{url}/status", timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def _check_flask() -> None:
    if importlib.util.find_spec("flask") is None:
        print(
            "\nFlask is not installed. Run:\n"
            "  pip install flask\n"
            "or, from the project root with the venv active:\n"
            "  pip install -r requirements.txt\n"
        )
        sys.exit(1)


def _python_executable() -> str:
    """Return the current Python executable (already inside venv if activated)."""
    return sys.executable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    os.chdir(PROJECT_ROOT)
    _check_flask()

    port = _find_port()
    url = f"http://localhost:{port}"

    python = _python_executable()
    env = os.environ.copy()
    env["FLASK_APP"] = str(UI_APP)
    env["FLASK_ENV"] = "production"
    # Do not set WERKZEUG_RUN_MAIN: with Flask 3 / Werkzeug 3 that can force a code path
    # that expects WERKZEUG_SERVER_FD (reloader socket inheritance) and crashes with KeyError.
    # --no-reload is sufficient to disable the reloader.

    cmd = [python, "-m", "flask", "--app", str(UI_APP), "run", "--port", str(port), "--no-reload"]

    print(f"Starting STS Test Runner on {url} …")

    server = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        # Let Flask output flow to the terminal so the user can see errors
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    # Graceful shutdown on Ctrl-C
    def _shutdown(signum=None, frame=None):
        print("\nShutting down…")
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    # Wait for Flask to be ready, then open browser
    if _wait_for_server(url):
        print(f"Server ready → opening {url}")
        webbrowser.open(url)
    else:
        print(f"Server did not respond in time. Open {url} manually.")

    # Block until the server exits on its own (shouldn't happen normally)
    try:
        server.wait()
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
