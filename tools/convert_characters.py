"""Converts Quaternius "Universal Base Characters" + "Universal Animation Library" 1 & 2 (all CC0)
into mods/core/models/humans/.   python tools/convert_characters.py   (needs panda3d-gltf)

Output:  humans/male.bam, humans/female.bam   (bodies, no animations)
         humans/anims.bam                      (the animations the game uses, shared by every body)
         humans/hair_*.bam                     (static hair, attached to the head bone at runtime)
         textures/human_*.png                  (resized to 1024)
"""
import glob
import json
import os
import shutil

from panda3d.core import Filename, NodePath, PNMImage, loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\nbam-texture-mode relative\nnotify-level error")
import gltf  # noqa: F401
from direct.showbase.ShowBase import ShowBase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets_src")
OUT = os.path.join(ROOT, "mods", "core", "models")
HUM = os.path.join(OUT, "humans")
TEX = os.path.join(OUT, "textures")
os.makedirs(HUM, exist_ok=True)
os.makedirs(TEX, exist_ok=True)
base = ShowBase()

KEEP_ANIMS = ["Idle_Loop", "Walk_Loop", "Jog_Fwd_Loop", "Sprint_Loop", "Death01", "Hit_Chest", "Hit_Head",
              "Pistol_Idle_Loop", "Pistol_Aim_Neutral", "Pistol_Shoot", "Pistol_Reload", "Punch_Jab", "Idle_Talking_Loop",
              "Idle_FoldArms_Loop", "Yes", "Idle_No_Loop", "Zombie_Idle_Loop", "Zombie_Scratch", "Zombie_Walk_Fwd_Loop",
              "Consume", "Interact", "Jump_Loop", "Walk_Carry_Loop", "Crouch_Idle_Loop", "Sitting_Idle_Loop", "LayToIdle"]


def find(pattern):
    hits = glob.glob(os.path.join(SRC, pattern), recursive=True)
    if not hits:
        raise SystemExit(f"missing {pattern} - extract the Universal packs into assets_src/ first")
    return hits[0]


def load(path):
    return base.loader.loadModel(Filename.fromOsSpecific(path), noCache=True)


def small_texture(src, name, size=1024):
    dest = os.path.join(TEX, name)
    img = PNMImage()
    img.read(Filename.fromOsSpecific(src))
    if img.getXSize() > size:
        out = PNMImage(size, size * img.getYSize() // img.getXSize(), img.getNumChannels())
        out.quickFilterFrom(img)
        img = out
    img.write(Filename.fromOsSpecific(dest))
    return dest


def retexture(np, prefix):
    """Point every texture at a resized copy in textures/ (keeps the download small)."""
    for tex in np.findAllTextures():
        src = tex.getFullpath().toOsSpecific()
        if not os.path.isfile(src):
            continue
        base_name = os.path.basename(src).replace("_png.png", ".png")
        name = base_name if base_name.startswith(prefix) else prefix + base_name
        dest = small_texture(src, name)
        tex.setFilename(Filename.fromOsSpecific(dest))
        tex.setFullpath(Filename.fromOsSpecific(dest))
        tex.read(Filename.fromOsSpecific(dest))


meta = {}
for gender in ("Male", "Female"):
    body = load(find(rf"ubc\**\Godot - UE\Superhero_{gender}_FullBody.gltf"))
    retexture(body, "human_")
    dest = os.path.join(HUM, gender.lower() + ".bam")
    body.writeBamFile(Filename.fromOsSpecific(dest))
    a, b = body.getTightBounds()
    meta[f"humans/{gender.lower()}"] = {"kind": "human", "facing": 180, "height": round(b[2] - a[2], 3)}
    print("body", gender, round(b[2] - a[2], 2), "m")

# light-skin variants of the base colour (swapped at runtime)
for src_name, dst_name in (("T_Superhero_Male_Ligh.png", "human_T_Superhero_Male_Light.png"),
                           ("T_Superhero_Female_Light_BaseColor.png", "human_T_Superhero_Female_Light.png"),
                           ("T_Superhero_Male_Dark.png", "human_T_Superhero_Male_Dark.png"),
                           ("T_Superhero_Female_Dark_BaseColor.png", "human_T_Superhero_Female_Dark.png")):
    small_texture(find(rf"ubc\**\Textures\{src_name}"), dst_name)

anims = NodePath("anims")
seen = set()
for lib in ("ual1", "ual2"):
    m = load(find(rf"{lib}\**\*.glb"))
    for bn in m.findAllMatches("**/+AnimBundleNode"):
        name = bn.node().getBundle().getName()
        if name in KEEP_ANIMS and name not in seen:
            seen.add(name)
            bn.copyTo(anims)
anims.writeBamFile(Filename.fromOsSpecific(os.path.join(HUM, "anims.bam")))
missing = [a for a in KEEP_ANIMS if a not in seen]
print(f"anims: {len(seen)} kept", "missing:" if missing else "", missing or "")
meta["humans/anims"] = {"kind": "anims", "names": sorted(seen)}

for path in glob.glob(os.path.join(SRC, "ubc", "**", "Origin at 0", "**", "*.gltf"), recursive=True):
    name = os.path.splitext(os.path.basename(path))[0]
    hair = load(path)
    retexture(hair, "human_")
    hair.flattenStrong()
    hair.writeBamFile(Filename.fromOsSpecific(os.path.join(HUM, "hair_" + name.lower() + ".bam")))
    meta[f"humans/hair_{name.lower()}"] = {"kind": "hair"}
print("hair:", [k for k in meta if "hair" in k])

mj = os.path.join(OUT, "models.json")
data = json.load(open(mj)) if os.path.isfile(mj) else {"models": {}}
data["models"].update(meta)
data["source"] = data.get("source", "") + " + Quaternius Universal Base Characters / Animation Library 1+2 (CC0)"
json.dump(data, open(mj, "w"), indent=1)
shutil.copyfile(find(r"ubc\**\License_Standard.txt"), os.path.join(OUT, "LICENSE-quaternius-universal.txt"))
print("done")
