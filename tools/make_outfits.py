"""Paints clothing onto the Universal Base Characters' skin textures (they ship in underwear).

Each texture pixel gets a body region from the bones that move it (torso, arms, hands, legs, feet), then
shirts / sleeves / trousers / boots / gloves are painted in, keeping the texture's shading.
    python tools/make_outfits.py        (needs: pip install pillow  - only for this tool, not the game)
Writes mods/core/models/textures/outfit_<gender>_<skin>_<outfit>.jpg and the outfit list in models.json.
"""
import json
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from panda3d.core import Filename, GeomVertexReader, loadPrcFileData

loadPrcFileData("", "window-type none\naudio-library-name null\nnotify-level error")
from direct.showbase.ShowBase import ShowBase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "mods", "core", "models")
TEX = os.path.join(MODELS, "textures")
SIZE = 512
base = ShowBase()

SKIN, TORSO, UPPERARM, LOWERARM, HANDS, HIPS, CALF, FEET = range(8)


def region(joint):
    j = joint.lower()
    if any(k in j for k in ("index", "middle", "ring", "pinky", "thumb", "hand")):
        return HANDS
    if "lowerarm" in j:
        return LOWERARM
    if "upperarm" in j:
        return UPPERARM
    if "spine" in j or "clavicle" in j:
        return TORSO
    if "pelvis" in j or "thigh" in j:
        return HIPS
    if "calf" in j:
        return CALF
    if "foot" in j or "ball" in j:
        return FEET
    return SKIN


def label_map(gender):
    body = base.loader.loadModel(Filename.fromOsSpecific(os.path.join(MODELS, "humans", gender + ".bam")))
    gnp = max(body.findAllMatches("**/+GeomNode"), key=lambda g: g.node().getGeom(0).getVertexData().getNumRows())
    img = Image.new("L", (SIZE, SIZE), SKIN)
    draw = ImageDraw.Draw(img)
    for geom in gnp.node().getGeoms():
        vd = geom.getVertexData()
        table = vd.getTransformBlendTable()
        uvname = "texcoord" if vd.getFormat().hasColumn("texcoord") else "texcoord.0"
        uv = GeomVertexReader(vd, uvname)
        tb = GeomVertexReader(vd, "transform_blend")
        uvs, labels = [], []
        while not uv.isAtEnd():
            u = uv.getData2()
            uvs.append((u[0] * SIZE, (1 - u[1]) * SIZE))
            blend = table.getBlend(tb.getData1i())
            votes = {}
            for i in range(blend.getNumTransforms()):
                r = region(blend.getTransform(i).getJoint().getName())
                votes[r] = votes.get(r, 0) + blend.getWeight(i)
            labels.append(max(votes, key=votes.get) if votes else SKIN)
        for p in range(geom.getNumPrimitives()):
            prim = geom.getPrimitive(p).decompose()
            for t in range(prim.getNumPrimitives()):
                s, e = prim.getPrimitiveStart(t), prim.getPrimitiveEnd(t)
                idx = [prim.getVertex(k) for k in range(s, e)]
                labs = [labels[k] for k in idx]
                lab = max(set(labs), key=labs.count)
                draw.polygon([uvs[k] for k in idx], fill=lab, outline=lab)
    return img.filter(ImageFilter.ModeFilter(3))


OUTFITS = {
    # players: shirt in their colour (PLAYER_COLORS order), tactical trousers, boots
    "p0": dict(shirt=(214, 120, 40), sleeves="long", pants=(58, 60, 64), shoes=(30, 28, 26), gloves=True),
    "p1": dict(shirt=(52, 120, 200), sleeves="long", pants=(70, 66, 56), shoes=(30, 28, 26)),
    "p2": dict(shirt=(70, 150, 70), sleeves="short", pants=(56, 62, 70), shoes=(35, 30, 26), gloves=True),
    "p3": dict(shirt=(190, 50, 50), sleeves="long", pants=(48, 48, 52), shoes=(26, 24, 22)),
    "p4": dict(shirt=(130, 80, 190), sleeves="short", pants=(66, 62, 56), shoes=(30, 28, 26)),
    "p5": dict(shirt=(215, 185, 50), sleeves="long", pants=(60, 64, 70), shoes=(40, 34, 28), gloves=True),
    "p6": dict(shirt=(50, 180, 170), sleeves="short", pants=(52, 54, 58), shoes=(28, 26, 24)),
    "p7": dict(shirt=(220, 100, 160), sleeves="long", pants=(58, 56, 66), shoes=(30, 28, 26)),
    # townsfolk
    "c0": dict(shirt=(150, 40, 36), sleeves="long", pants=(48, 62, 104), shoes=(70, 50, 34)),     # flannel + jeans
    "c1": dict(shirt=(80, 110, 160), sleeves="long", pants=(150, 130, 96), shoes=(60, 44, 30)),   # denim shirt + khakis
    "c2": dict(shirt=(225, 222, 210), sleeves="short", pants=(56, 72, 110), shoes=(220, 220, 220)),  # white tee + jeans
    "c3": dict(shirt=(84, 98, 62), sleeves="long", pants=(70, 62, 52), shoes=(40, 32, 26)),     # field jacket
    "c4": dict(shirt=(120, 122, 128), sleeves="long", pants=(40, 40, 44), shoes=(30, 30, 30)),   # grey hoodie
    "c5": dict(shirt=(54, 70, 96), sleeves="long", pants=(64, 56, 48), shoes=(50, 36, 26)),      # navy jacket
    # zombies: ragged clothes, sickly skin, bare feet
    "z0": dict(shirt=(90, 86, 80), sleeves="short", pants=(46, 56, 84), shoes=None, skin=(0.55, 0.72, 0.48)),
    "z1": dict(shirt=(62, 70, 58), sleeves="none", pants=(70, 64, 54), shoes=None, skin=(0.6, 0.68, 0.5)),
    "z2": dict(shirt=(120, 60, 50), sleeves="long", pants=(40, 44, 50), shoes=(30, 28, 26), skin=(0.5, 0.66, 0.5)),
}
SKIN_TEX = {("male", "light"): "human_T_Superhero_Male_Light.png", ("male", "dark"): "human_T_Superhero_Male_Dark.png",
            ("female", "light"): "human_T_Superhero_Female_Light.png", ("female", "dark"): "human_T_Superhero_Female_Dark.png"}


def paint(skin_img, labels, o):
    gray = skin_img.convert("L")
    mean = sum(i * c for i, c in enumerate(gray.histogram())) / (SIZE * SIZE)
    shade = gray.point(lambda v: max(0, min(255, int(205 + (v - mean) * 0.55)))).convert("RGB")
    out = skin_img.copy()
    if o.get("skin"):
        r, g, b = o["skin"]
        tint = Image.new("RGB", out.size, (int(255 * r), int(255 * g), int(255 * b)))
        out = ImageChops.multiply(out, tint)

    def fill(regions, color):
        if color is None:
            return
        layer = ImageChops.multiply(Image.new("RGB", out.size, tuple(min(255, int(c * 1.25)) for c in color)), shade)
        mask = labels.point(lambda v: 255 if v in regions else 0)
        out.paste(layer, (0, 0), mask)

    sleeves = {"long": (UPPERARM, LOWERARM), "short": (UPPERARM,), "none": ()}[o.get("sleeves", "long")]
    fill((TORSO,) + sleeves, o.get("shirt"))
    fill((HIPS, CALF), o.get("pants"))
    fill((FEET,), o.get("shoes"))
    if o.get("gloves"):
        fill((HANDS,), (34, 32, 30))
    return out


meta = {}
for gender in ("male", "female"):
    labels = label_map(gender)
    counts = labels.histogram()[:8]
    print(gender, "label pixels:", counts)
    for skin in ("light", "dark"):
        skin_img = Image.open(os.path.join(TEX, SKIN_TEX[(gender, skin)])).convert("RGB").resize((SIZE, SIZE))
        for oid, o in OUTFITS.items():
            name = f"outfit_{gender}_{skin}_{oid}.jpg"
            paint(skin_img, labels, o).save(os.path.join(TEX, name), quality=88)
            meta[name] = 1
mj = os.path.join(MODELS, "models.json")
data = json.load(open(mj))
data["models"]["humans/outfits"] = {"kind": "outfits", "ids": list(OUTFITS)}
json.dump(data, open(mj, "w"), indent=1)
print("wrote", len(meta), "outfit textures")
