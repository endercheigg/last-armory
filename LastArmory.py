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

def selftest():
    """Headless check that the engine, models and animations load (used by CI and after packaging)."""
    from panda3d.core import loadPrcFileData
    loadPrcFileData("", "window-type none\naudio-library-name null\nnotify-level warning\ndefault-directnotify-level warning")
    from direct.showbase.ShowBase import ShowBase
    from armory.client import assets
    from armory.content import load_content
    base = ShowBase()
    assets.init(ROOT, base.loader)
    content = load_content(os.path.join(ROOT, "mods"), load_scripts=False)
    assert not content["errors"], content["errors"]
    gun = assets.build_gun_mesh(base.render, {"receiver": "rcv_rifle", "barrel": "brl_long", "magazine": "mag_ext"},
                                content["parts"], lambda parent, part: parent.attachNewNode("part"))
    assert gun, "gun model failed to load"
    ch = assets.AnimChar(base.render, assets.PLAYER_MODELS[0])
    assert "Walk_Gun" in ch.anims, ch.anims
    z = assets.AnimChar(base.render, "zombies/basic", zombie=True)
    print(f"selftest ok: {len(content['parts'])} parts, {len(assets._index)} models, {len(ch.anims)} survivor anims, {len(z.anims)} zombie anims")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    if "--server" in sys.argv:
        from armory.server import main
        args = [a for a in sys.argv[1:] if a != "--server"]
        main(ROOT, args)
    else:
        from armory.client.app import run
        App = run(ROOT)
        App().run()
