"""Launch LAST ARMORY:  python LastArmory.py          (game)
                      python LastArmory.py --server  (dedicated server, same options as ArmoryServer.py)"""
import os
import sys

if getattr(sys, "frozen", False):
    # macOS .app bundles keep data files in Contents/Resources (sys._MEIPASS); Windows keeps them next to the exe
    ROOT = sys._MEIPASS if sys.platform == "darwin" and hasattr(sys, "_MEIPASS") else os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

if __name__ == "__main__":
    if "--server" in sys.argv:
        from armory.server import main
        args = [a for a in sys.argv[1:] if a != "--server"]
        main(ROOT, args)
    else:
        from armory.client.app import run
        App = run(ROOT)
        App().run()
