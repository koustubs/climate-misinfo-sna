#!/usr/bin/env bash
# Double-click on macOS (or run `bash START_MAC_LINUX.command` in a terminal on Mac/Linux).
cd "$(dirname "$0")" || exit 1
echo
echo "============================================================"
echo "  Climate Misinformation - Social Network Analysis demo"
echo "============================================================"
echo

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "[!] Python 3.10+ not found. Install it from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Enter to close..." _; exit 1
fi
echo "Using $($PY --version)"

if [ ! -x ".venv/bin/python" ]; then
  echo "First run: creating a private Python environment in .venv ..."
  "$PY" -m venv .venv || { echo "[!] Could not create the virtual environment."; read -r -p "Press Enter..." _; exit 1; }
fi
if [ ! -f ".venv/setup_done.txt" ]; then
  echo "First run: installing libraries (needs internet once, 1-3 minutes)..."
  .venv/bin/python -m pip install --upgrade pip --disable-pip-version-check
  .venv/bin/python -m pip install -r requirements.txt --disable-pip-version-check || {
    echo "[!] Installing the libraries failed. Check the internet connection and try again."
    read -r -p "Press Enter to close..." _; exit 1; }
  echo done > .venv/setup_done.txt
fi

echo
echo "Starting the app - your browser will open automatically."
exec .venv/bin/python app.py
