"""Converts the downloaded CC0 model packs (assets_src/) into game-ready .bam files in mods/core/models/.

    python tools/convert_assets.py

Packs (all CC0 / public domain):
  - Quaternius "Zombie Apocalypse Kit" (characters, zombies, props, vehicles)  https://quaternius.com
  - Quaternius "Ultimate Gun Pack" (40 guns)                                   https://quaternius.com
  - Kenney "Furniture Kit" (shop interior)                                      https://kenney.nl
Needs:  pip install panda3d panda3d-gltf
"""
import glob
import json
import os
import shutil
import sys

from panda3d.core import Filename, LMatrix4f, NodePath, loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\nload-file-type p3assimp\nbam-texture-mode relative")
import gltf  # noqa: F401  (registers the .gltf/.glb loader)
from direct.showbase.ShowBase import ShowBase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets_src")
OUT = os.path.join(ROOT, "mods", "core", "models")
base = ShowBase()
meta = {"source": "Quaternius Zombie Apocalypse Kit + Ultimate Gun Pack, Kenney Furniture Kit (all CC0)", "models": {}}

WEAPON_NODES = {"CUBezierCurve.001", "Cylinder.005", "Cylinder.027", "Cube.064", "Cube.002", "Cube.010", "Cube.007",
                "Cylinder.022", "Cube.008", "Cylinder.014"}


def find(pattern):
    hits = glob.glob(os.path.join(SRC, pattern), recursive=True)
    if not hits:
        raise SystemExit(f"missing {pattern} - did you download and drop the zips into assets_src/ ?")
    return hits[0]


def load(path):
    return base.loader.loadModel(Filename.fromOsSpecific(path), noCache=True)


def save(np, rel, info):
    dest = os.path.join(OUT, rel + ".bam")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for tex in np.findAllTextures():
        src = tex.getFullpath().toOsSpecific()
        if not os.path.isfile(src):
            name = os.path.basename(tex.getFilename().toOsSpecific()) or tex.getName()
            hits = glob.glob(os.path.join(SRC, "**", name), recursive=True) or                 glob.glob(os.path.join(SRC, "**", name + ".png"), recursive=True)
            src = hits[0] if hits else src
        if os.path.isfile(src):
            tdir = os.path.join(OUT, "textures")
            os.makedirs(tdir, exist_ok=True)
            tdest = os.path.join(tdir, os.path.basename(src))
            if not os.path.isfile(tdest):
                shutil.copyfile(src, tdest)
            tex.setFilename(Filename.fromOsSpecific(tdest))
            tex.setFullpath(Filename.fromOsSpecific(tdest))
    np.writeBamFile(Filename.fromOsSpecific(dest))
    a, b = np.getTightBounds()
    info.update(size=[round(b[i] - a[i], 3) for i in range(3)], min=[round(a[i], 3) for i in range(3)])
    meta["models"][rel] = info
    print(f"  {rel:40s} {info['size']}")


def ensure_zak():
    if not glob.glob(os.path.join(SRC, "zak")):
        raise SystemExit("extract the packs first (see mac/README or ask the dev)")


# ---------------------------------------------------------------- characters (keep animations)
print("characters")
for name in ("Lis", "Matt", "Sam", "Shaun"):
    np = load(find(rf"zak\**\Characters\glTF\Characters_{name}.gltf"))
    for g in np.findAllMatches("**/+GeomNode"):
        if g.getName() in WEAPON_NODES:
            g.removeNode()
    save(np, f"chars/{name.lower()}", {"kind": "character", "facing": 180})
for name in ("Basic", "Chubby", "Arm", "Ribcage"):
    np = load(find(rf"zak\**\Characters\glTF\Zombie_{name}.gltf"))
    save(np, f"zombies/{name.lower()}", {"kind": "zombie", "facing": 180})

def vertices(np):
    from panda3d.core import GeomVertexReader
    pts = []
    for gnp in np.findAllMatches("**/+GeomNode"):
        mat = gnp.getMat(np)
        for geom in gnp.node().getGeoms():
            r = GeomVertexReader(geom.getVertexData(), "vertex")
            while not r.isAtEnd():
                v = mat.xformPoint(r.getData3())
                pts.append((v[0], v[1], v[2]))
    return pts


def gun_anchors(np, family):
    """Measure real mount points from the mesh: barrel tip, top of the receiver, underside of the handguard."""
    pts = vertices(np)
    ymax = max(p[1] for p in pts)
    L = ymax

    def window(y0, y1):
        return [p for p in pts if y0 * L <= p[1] <= y1 * L] or pts

    tip = [p for p in pts if p[1] >= ymax - 0.012 * L]
    mx = (min(p[0] for p in tip) + max(p[0] for p in tip)) / 2
    mz = (min(p[2] for p in tip) + max(p[2] for p in tip)) / 2
    pistol = family in ("Pistol", "Revolver")
    top_w = window(0.3, 0.5) if not pistol else window(0.35, 0.7)
    under_w = window(0.62, 0.82) if not pistol else window(0.6, 0.85)
    top_z = max(p[2] for p in top_w)
    under_z = min(p[2] for p in under_w)
    tw = [p for p in top_w if p[2] >= top_z - 0.004]
    return {"muzzle": [round(mx, 4), round(ymax, 4), round(mz, 4)],
            "top": [round(sum(p[0] for p in tw) / len(tw), 4), round((0.4 if not pistol else 0.55) * L, 4), round(top_z, 4)],
            "under": [round(mx, 4), round((0.72 if not pistol else 0.72) * L, 4), round(under_z, 4)],
            "bayonet": [round(mx, 4), round(ymax - 0.06 * L, 4), round(mz - 0.022, 4)]}


# ---------------------------------------------------------------- guns: point +Y, Z up, back end at y=0
print("guns")
LENGTH = {"Pistol": 0.22, "Revolver": 0.3, "SubmachineGun": 0.5, "Bullpup": 0.72, "AssaultRifle": 0.9,
          "AssaultRifle2": 0.92, "Shotgun": 1.0, "SniperRifle": 1.2}
ROT = LMatrix4f(0, 1, 0, 0,
                0, 0, 1, 0,
                1, 0, 0, 0,
                0, 0, 0, 1)
for path in sorted(glob.glob(os.path.join(SRC, "guns", "**", "OBJ", "*.obj"), recursive=True)):
    name = os.path.splitext(os.path.basename(path))[0]
    family = name.rsplit("_", 1)[0]
    if family.startswith("Shotgun"):
        family = "Shotgun"
    raw = load(path)
    holder = NodePath("gun")
    raw.reparentTo(holder)
    raw.setMat(ROT)
    holder.flattenStrong()
    a, b = holder.getTightBounds()
    L = LENGTH.get(family, 0.8)
    if name == "Shotgun_SawedOff":
        L = 0.6
    s = L / (b[1] - a[1])
    for c in holder.getChildren():
        c.setPos(-(a[0] + b[0]) / 2, -a[1], -(a[2] + b[2]) / 2)
        c.setScale(1)
    holder.setScale(s)
    holder.flattenStrong()
    info = {"kind": "gun", "family": family, "length": round(L, 3)}
    info.update(gun_anchors(holder, family))
    save(holder, f"guns/{name}", info)

# ---------------------------------------------------------------- props + vehicles (metres already)
print("props")
for path in sorted(glob.glob(os.path.join(SRC, "zak", "**", "Environment", "glTF", "*.gltf"), recursive=True)) + \
        sorted(glob.glob(os.path.join(SRC, "zak", "**", "Vehicles", "glTF", "*.gltf"), recursive=True)):
    name = os.path.splitext(os.path.basename(path))[0]
    if name.startswith("Blood"):
        continue
    np = load(path)
    np.flattenStrong()
    save(np, f"props/{name}", {"kind": "prop"})

# ---------------------------------------------------------------- shop furniture (Kenney, scaled x2.2 to metres)
print("furniture")
KEEP = ["bookcaseOpen", "bookcaseOpenLow", "bookcaseClosedWide", "kitchenBar", "kitchenBarEnd", "kitchenCabinet", "pottedPlant",
        "plantSmall1", "plantSmall2", "plantSmall3", "lampSquareFloor", "lampRoundFloor", "lampSquareCeiling", "lampWall",
        "rugRectangle", "rugRound", "rugDoormat", "tableCross", "table", "desk", "chairDesk", "stoolBar", "cardboardBoxOpen",
        "cardboardBoxClosed", "trashcan", "radio", "speaker", "coatRackStanding", "sideTable", "books", "laptop",
        "computerScreen", "televisionVintage", "benchCushion", "ceilingFan", "bedSingle", "lampSquareTable",
        "bookcaseClosed", "kitchenFridgeSmall", "kitchenStove", "kitchenCoffeeMachine", "kitchenMicrowave"]
for name in KEEP:
    np = load(find(rf"kenney\**\{name}.glb"))
    holder = NodePath("f")
    np.reparentTo(holder)
    np.setScale(2.2)
    holder.flattenStrong()
    save(holder, f"furniture/{name}", {"kind": "furniture"})

with open(os.path.join(OUT, "models.json"), "w") as f:
    json.dump(meta, f, indent=1)
for lic, dest in ((find(r"zak\**\License.txt"), "LICENSE-quaternius-zombie-kit.txt"),
                  (find(r"guns\**\License.txt"), "LICENSE-quaternius-guns.txt"),
                  (find(r"kenney\License.txt"), "LICENSE-kenney-furniture.txt")):
    shutil.copyfile(lic, os.path.join(OUT, dest))
print(f"done: {len(meta['models'])} models -> {OUT}")
