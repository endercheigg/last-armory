#!/bin/bash
# Runs a LAST ARMORY dedicated server in this Terminal window (no graphics needed).
cd "$(dirname "$0")"
GAME_DIR="$(pwd)"
[ -f "$GAME_DIR/LastArmory.py" ] || GAME_DIR="$(cd .. && pwd)"
cd "$GAME_DIR"
exec python3 ArmoryServer.py "$@"
