"""Content for the 'materials + events' update (safe to re-run):
  - real materials on every box of the town, the shop and both wasteland maps
  - The Collector's stall in the market (special gun contracts)
    python tools/author_v3.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "mods", "core")


def load(rel):
    with open(os.path.join(CORE, rel)) as f:
        return json.load(f)


def save(rel, data):
    with open(os.path.join(CORE, rel), "w") as f:
        json.dump(data, f, indent=1)


def set_mats(boxes, by_color):
    for b in boxes:
        m = by_color.get(b.get("color"))
        if m and not b.get("mesh"):
            b["mat"] = m


# ------------------------------------------------------------------ shop
s = load("shops/standard.json")
for b in s["boxes"]:
    if b.get("color") == "#8a7b68":
        b["mat"] = "brick"
    elif b.get("color") == "#6b5d4f":
        b["mat"] = "corrugated"
    elif b.get("color") == "#8c7a64":
        b["mat"] = "planks"
    elif b.get("color") in ("#4e3a28", "#7a5634"):
        b["mat"], b["tint"] = "planks", "#c9a27a"
    elif b.get("color") in ("#2f3540", "#333333", "#4a5058", "#3c4a5a"):
        b["mat"], b["tint"] = "metal", "#8c939c"
save("shops/standard.json", s)

# ------------------------------------------------------------------ town
t = load("towns/haven.json")
t["groundMat"] = "paving"
COLLECTOR = {"id": "collector", "name": "The Collector", "kind": "collector", "x": 84, "y": 51.4, "h": 180,
             "color": "#7d4bd1", "items": []}
t["vendors"] = [v for v in t["vendors"] if v["id"] != "collector"] + [COLLECTOR]
t["boxes"] = [b for b in t["boxes"] if not (b.get("stall") and 82 < b["x"] < 86.5)]
x = COLLECTOR["x"]
t["boxes"] += [
    {"x": x - 1.7, "y": 52.0, "z": 0, "w": 3.4, "d": 0.7, "h": 1.0, "color": "#7a5634", "stall": True},
    {"x": x - 1.8, "y": 54.4, "z": 0, "w": 3.6, "d": 0.2, "h": 2.8, "color": "#6b5a48", "stall": True},
    {"x": x - 1.85, "y": 52.0, "z": 0, "w": 0.15, "d": 2.6, "h": 2.8, "color": "#5a4a3a", "stall": True},
    {"x": x + 1.7, "y": 52.0, "z": 0, "w": 0.15, "d": 2.6, "h": 2.8, "color": "#5a4a3a", "stall": True},
]
for b in t["boxes"]:
    c = b.get("color")
    if b.get("stall"):
        b["mat"] = "planks" if b["h"] <= 1.0 else "siding"
        b["tint"] = "#d9b48a" if b["h"] <= 1.0 else "#bfa58a"
    elif c == "#6f665a":
        b["mat"], b["tint"] = "concrete", "#d8d0c4"
    elif c in ("#7d7a72", "#9a968c"):
        b["mat"] = "concrete"
    elif c == "#b8862f":
        b["mat"], b["tint"] = "metal", "#e0b050"
    elif c in ("#8a6a3d", "#6b4a2b"):
        b["mat"], b["tint"] = "planks", "#c9a27a"
    elif c in ("#5a6a4a", "#4a5a3a"):
        b["mat"], b["tint"] = "metal", "#9db08a"
save("towns/haven.json", t)

# ------------------------------------------------------------------ wasteland
for name, ground, by_color in (
        ("foundry", "asphalt", {"#6b6f75": "concrete", "#3d6b5a": "metal", "#6b5a45": "siding", "#4a4f57": "corrugated"}),
        ("shipyard", "concrete", {"#7d7a72": "concrete", "#6f6a60": "corrugated", "#6b6f75": "metal"})):
    a = load(f"arenas/{name}.json")
    a["groundMat"] = ground
    set_mats(a["boxes"], by_color)
    for b in a["boxes"]:
        if b.get("mat") == "concrete":
            b["tint"] = "#a3a19c"
    for b in a["boxes"]:
        if b.get("color") == "#3d6b5a":
            b["tint"] = "#8fbfa8"
    save(f"arenas/{name}.json", a)
print("v3 content written")
