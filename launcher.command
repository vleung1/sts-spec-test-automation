#!/usr/bin/env bash
# STS Test Runner — macOS double-click launcher
# Double-click this file in Finder to start the test runner UI.
# It activates the .venv if present, then launches the browser-based UI.

set -euo pipefail

# Resolve the project root (the directory containing this file)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if it exists
if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  echo "Activated .venv"
fi

# Fall back to python3 if python is not on PATH
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" &>/dev/null; then
  echo "Python not found. Install Python 3.9+ and try again."
  read -r -p "Press Enter to close…"
  exit 1
fi

"$PYTHON" launcher.py

# Keep the terminal window open if something went wrong
if [ $? -ne 0 ]; then
  echo ""
  read -r -p "Press Enter to close…"
fi
