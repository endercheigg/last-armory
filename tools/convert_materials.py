"""Converts ambientCG materials (CC0, https://ambientcg.com) into the game's building textures.

Put the 1K-JPG zips in assets_src/ambientcg/ and run:   python tools/convert_materials.py   (needs pillow - tool only)
Writes mods/core/models/materials/<name>_color.jpg (+ ambient occlusion baked in) and <name>_normal.jpg.
"""
import glob
import io
import json
import os
import sys
import zipfile

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets_src", "ambientcg")
OUT = os.path.join(ROOT, "mods", "core", "models", "materials")

# game material name -> (ambientCG asset, metres one texture repeat covers)
MATERIALS = {
    "brick": ("Bricks105", 2.4),
    "plaster": ("PaintedPlaster017", 3.0),
    "concrete": ("Concrete034", 3.0),
    "corrugated": ("CorrugatedSteel005", 2.0),
    "metal": ("MetalPlates006", 2.0),
    "siding": ("WoodSiding009", 2.0),
    "planks": ("WoodFloor043", 2.0),
    "roof": ("RoofingTiles013A", 2.5),
    "asphalt": ("Asphalt031", 4.0),
    "paving": ("PavingStones138", 2.5),
}


def member(z, suffix):
    for n in z.namelist():
        if n.endswith(suffix):
            return Image.open(io.BytesIO(z.read(n)))
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = {}
    for name, (asset, tile) in MATERIALS.items():
        hits = glob.glob(os.path.join(SRC, asset + "*.zip"))
        if not hits:
            print("missing", asset, "- skipped")
            continue
        with zipfile.ZipFile(hits[0]) as z:
            color = member(z, "_Color.jpg").convert("RGB")
            ao = member(z, "_AmbientOcclusion.jpg")
            normal = member(z, "_NormalGL.jpg").convert("RGB")
        if ao is not None:
            ao = ao.convert("L").resize(color.size).point(lambda v: int(150 + v * 105 / 255))
            color = ImageChops.multiply(color, Image.merge("RGB", (ao, ao, ao)))
        color.resize((1024, 1024), Image.LANCZOS).save(os.path.join(OUT, f"{name}_color.jpg"), quality=86)
        normal.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, f"{name}_normal.jpg"), quality=92)
        meta[name] = {"tile": tile, "source": f"ambientCG {asset} (CC0)"}
        print("wrote", name)
    with open(os.path.join(OUT, "materials.json"), "w") as f:
        json.dump(meta, f, indent=1)
    with open(os.path.join(OUT, "LICENSE-ambientcg.txt"), "w") as f:
        f.write("Textures from ambientCG.com, licensed under CC0 1.0 Universal (public domain).\n"
                + "\n".join(f"{k}: {v['source']}" for k, v in meta.items()) + "\n")


if __name__ == "__main__":
    sys.exit(main())
