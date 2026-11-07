#!/bin/bash
# LAST ARMORY launcher for macOS - double-click me.
# First launch installs Panda3D into ~/Library/Application Support/LastArmory/venv (about a minute).
cd "$(dirname "$0")"
GAME_DIR="$(pwd)"
[ -f "$GAME_DIR/LastArmory.py" ] || GAME_DIR="$(cd .. && pwd)"
VENV="$HOME/Library/Application Support/LastArmory/venv"

if ! command -v python3 >/dev/null 2>&1; then
  osascript -e 'display dialog "LAST ARMORY needs Python 3.\n\nInstall it from python.org, then double-click Play.command again." buttons {"OK"} default button 1' >/dev/null
  open "https://www.python.org/downloads/macos/"
  exit 1
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "First launch - setting things up (about a minute)..."
  mkdir -p "$(dirname "$VENV")"
  python3 -m venv "$VENV" || { echo "Could not create a Python environment."; read -n1; exit 1; }
fi
if ! "$VENV/bin/python" -c "import panda3d" 2>/dev/null; then
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV/bin/python" -m pip install "panda3d>=1.10.15" || { echo "Could not install Panda3D (needs internet)."; read -n1; exit 1; }
fi
exec "$VENV/bin/python" "$GAME_DIR/LastArmory.py" "$@"
