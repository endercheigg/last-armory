"""Run a LAST ARMORY dedicated server:  python ArmoryServer.py [--port 27030]"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
sys.path.insert(0, ROOT)

from armory.server import main

if __name__ == "__main__":
    main(ROOT, sys.argv[1:])
