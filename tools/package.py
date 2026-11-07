"""Make release zips.  python tools/package.py mac      -> dist/LastArmory-Mac.zip (source + launchers, exec bits set)
                       python tools/package.py windows  -> dist/LastArmory-Windows.zip (from the PyInstaller build in dist/LastArmory)"""
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SKIP_DIRS = {"__pycache__", "userdata", "dist", "build", ".buildenv", ".git", "assets_src"}
EXEC = {".command", ".sh"}


def add_tree(z, src, arc_prefix):
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith((".pyc", ".spec")) or f == "server_config.json":
                continue
            full = os.path.join(base, f)
            arc = os.path.join(arc_prefix, os.path.relpath(full, src)).replace("\\", "/")
            info = zipfile.ZipInfo.from_file(full, arc)
            mode = 0o755 if os.path.splitext(f)[1] in EXEC else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as fh:
                z.writestr(info, fh.read())


def mac():
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "LastArmory-Mac.zip")
    with zipfile.ZipFile(out, "w") as z:
        add_tree(z, ROOT, "LastArmory-Mac")
        for f in ("Play.command", "HostServer.command", "README-mac.md"):
            full = os.path.join(ROOT, "mac", f)
            info = zipfile.ZipInfo.from_file(full, f"LastArmory-Mac/{f}")
            info.external_attr = (0o100000 | (0o755 if f.endswith(".command") else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(full, "rb") as fh:
                z.writestr(info, fh.read())
    print("wrote", out)


def windows():
    src = os.path.join(DIST, "LastArmory")
    out = os.path.join(DIST, "LastArmory-Windows.zip")
    with zipfile.ZipFile(out, "w") as z:
        add_tree(z, src, "LastArmory")
    print("wrote", out)


if __name__ == "__main__":
    {"mac": mac, "windows": windows}[sys.argv[1]]()
