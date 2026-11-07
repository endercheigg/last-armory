#!/bin/bash
# Builds dist/LastArmory.app (and dist/LastArmory-macOS.zip) on a Mac.
# Usage:  bash mac/build_mac_app.sh        (needs python3; downloads PyInstaller + Panda3D into .buildenv)
set -e
cd "$(dirname "$0")/.."
python3 -m venv .buildenv
.buildenv/bin/python -m pip install --upgrade pip
.buildenv/bin/python -m pip install pyinstaller "panda3d>=1.10.15"
rm -rf build dist/LastArmory.app
.buildenv/bin/pyinstaller --noconfirm --windowed --name "LastArmory" \
  --collect-binaries panda3d --add-data "mods:mods" \
  --osx-bundle-identifier com.lastarmory.game LastArmory.py
# ad-hoc signature so Apple Silicon will run it (still unsigned for Gatekeeper: right-click > Open the first time)
codesign --force --deep -s - dist/LastArmory.app || true
cp README.md MODDING.md dist/ 2>/dev/null || true
(cd dist && rm -f LastArmory-macOS.zip && ditto -c -k --keepParent LastArmory.app LastArmory-macOS.zip)
echo
echo "Done:  dist/LastArmory.app   (zipped: dist/LastArmory-macOS.zip)"
echo "Host a dedicated server from the app:  dist/LastArmory.app/Contents/MacOS/LastArmory --server"
