"""Content for the 'workshop' update (safe to re-run):
  - more attachments, so every part category has at least 4 different parts at the supplier
  - a service window in the shop's front wall (customers hand over dirty guns to be cleaned)
    python tools/author_v4.py
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


BLACK, DARK, STEEL, WOOD, BRASS = "#18191c", "#232529", "#8f959d", "#6b4428", "#b8933a"
NEW_PARTS = [
    {"id": "stk_wire", "slot": "stock", "name": "Wire Stock", "tier": 0, "description": "Bent steel rod. Better than nothing.",
     "mul": {"recoil": 0.88}, "model": [
        {"t": "cyl", "p": [0, -0.11, 0.004], "r": 0.005, "l": 0.22, "c": STEEL},
        {"t": "cyl", "p": [0, -0.11, -0.05], "r": 0.005, "l": 0.22, "c": STEEL},
        {"t": "cyl", "p": [0, -0.22, -0.023], "r": 0.005, "l": 0.06, "c": STEEL, "axis": "z"},
        {"p": [0, -0.225, -0.023], "s": [0.03, 0.012, 0.07], "c": BLACK}]},
    {"id": "stk_wood", "slot": "stock", "name": "Walnut Stock", "tier": 2, "description": "Classic hunting wood. Steady shots.",
     "mul": {"recoil": 0.6, "spread": 0.88}, "model": [
        {"t": "prism", "x": 0.0, "w": 0.04, "pts": [[0.0, 0.01], [-0.12, 0.014], [-0.3, 0.02], [-0.32, 0.018], [-0.32, -0.1],
                                                   [-0.28, -0.105], [-0.14, -0.05], [-0.04, -0.045], [0.0, -0.03]], "c": WOOD},
        {"t": "prism", "x": 0.0, "w": 0.044, "pts": [[-0.32, 0.02], [-0.335, 0.02], [-0.335, -0.102], [-0.32, -0.102]], "c": "#2a1a10"}]},
    {"id": "sgt_peep", "slot": "sight", "name": "Peep Sight", "tier": 0, "description": "A little ring to aim through.",
     "mul": {"spread": 0.93}, "add": {"zoom": 0.1}, "model": [
        {"p": [0, 0.0, 0.006], "s": [0.02, 0.03, 0.012], "c": BLACK},
        {"p": [0, 0.0, 0.026], "s": [0.006, 0.006, 0.03], "c": DARK},
        {"t": "cyl", "p": [0, 0.0, 0.045], "r": 0.009, "l": 0.004, "c": DARK}]},
    {"id": "sgt_thermal", "slot": "sight", "name": "Thermal Scope", "tier": 4, "description": "Big zoom, rock-steady picture.",
     "mul": {"spread": 0.5}, "add": {"zoom": 2.4}, "model": [
        {"p": [0, 0.0, 0.006], "s": [0.03, 0.12, 0.012], "c": BLACK},
        {"p": [0, 0.0, 0.042], "s": [0.05, 0.16, 0.05], "c": "#2d3a2a"},
        {"t": "cyl", "p": [0, 0.095, 0.042], "r": 0.024, "l": 0.04, "c": BLACK},
        {"t": "cyl", "p": [0, 0.116, 0.042], "r": 0.02, "l": 0.002, "c": "#ff6a1a", "glow": True},
        {"t": "cyl", "p": [0, -0.1, 0.042], "r": 0.018, "l": 0.05, "c": BLACK},
        {"p": [0.03, 0.0, 0.042], "s": [0.01, 0.05, 0.03], "c": DARK}]},
    {"id": "grp_stub", "slot": "grip", "name": "Stubby Grip", "tier": 0, "description": "Short and cheap.",
     "mul": {"recoil": 0.88}, "model": [
        {"p": [0, 0, -0.005], "s": [0.024, 0.035, 0.01], "c": BLACK},
        {"t": "cyl", "p": [0, 0, -0.035], "r": 0.013, "l": 0.05, "c": DARK, "axis": "z"}]},
    {"id": "grp_gyro", "slot": "grip", "name": "Gyro Grip", "tier": 4, "description": "Spinning stabiliser. Almost no kick.",
     "mul": {"recoil": 0.35, "spread": 0.82}, "model": [
        {"p": [0, 0, -0.006], "s": [0.03, 0.06, 0.012], "c": BLACK},
        {"t": "cyl", "p": [0, 0, -0.05], "r": 0.016, "l": 0.08, "c": DARK, "axis": "z"},
        {"t": "cyl", "p": [0, 0, -0.06], "r": 0.03, "l": 0.012, "c": "#3fa7ff", "axis": "z", "glow": True}]},
    {"id": "bay_spike", "slot": "bayonet", "name": "Spike Bayonet", "tier": 0, "description": "A sharpened spike. Poke with F.",
     "mul": {}, "add": {"melee": 15}, "model": [
        {"p": [0, -0.005, -0.004], "s": [0.018, 0.012, 0.026], "c": DARK},
        {"t": "cyl", "p": [0, 0.07, 0.0], "r": 0.005, "l": 0.14, "c": STEEL, "r2": 0.0005}]},
    {"id": "bay_axe", "slot": "bayonet", "name": "Hatchet Blade", "tier": 3, "description": "Chop chop. (F)",
     "mul": {"moveSpeed": 0.97}, "add": {"melee": 65}, "model": [
        {"p": [0, -0.005, -0.004], "s": [0.024, 0.014, 0.034], "c": DARK},
        {"t": "prism", "x": 0.0, "w": 0.012, "pts": [[0.0, -0.01], [0.16, -0.01], [0.16, 0.006], [0.0, 0.006]], "c": WOOD},
        {"t": "prism", "x": 0.0, "w": 0.006, "pts": [[0.11, -0.01], [0.16, -0.01], [0.18, -0.07], [0.1, -0.06]], "c": STEEL}]},
]

a = load("parts/attachments.json")
plist = a if isinstance(a, list) else a["parts"]
ids = {p["id"] for p in NEW_PARTS}
plist[:] = [p for p in plist if p["id"] not in ids] + NEW_PARTS
save("parts/attachments.json", a)

# ------------------------------------------------------------------ shop: a service window left of the door
s = load("shops/standard.json")
WIN_X0, WIN_X1, WIN_Z0, WIN_Z1 = 1.2, 3.4, 1.05, 2.3
s["boxes"] = [b for b in s["boxes"] if not b.get("svc") and not (b["x"] == 0 and b["y"] == 0 and b["w"] == 4.7 and b["h"] == 4.1)]
wall = {"y": 0, "z": 0, "d": 0.3, "color": "#8a7b68", "mat": "brick", "svc": True}
s["boxes"] += [
    dict(wall, x=0, w=WIN_X0, h=4.1),
    dict(wall, x=WIN_X1, w=4.7 - WIN_X1, h=4.1),
    dict(wall, x=WIN_X0, w=WIN_X1 - WIN_X0, h=WIN_Z0),
    dict(wall, x=WIN_X0, z=WIN_Z1, w=WIN_X1 - WIN_X0, h=4.1 - WIN_Z1),
    # wooden sill / counter on both sides of the opening
    {"x": WIN_X0, "y": -0.25, "z": WIN_Z0, "w": WIN_X1 - WIN_X0, "d": 0.85, "h": 0.06, "color": "#7a5634", "mat": "planks",
     "tint": "#c9a27a", "svc": True},
    # little roof over the window
    {"x": WIN_X0 - 0.15, "y": -0.55, "z": WIN_Z1 + 0.25, "w": WIN_X1 - WIN_X0 + 0.3, "d": 0.6, "h": 0.06, "color": "#6b5d4f",
     "mat": "corrugated", "svc": True},
]
s["service"] = [(WIN_X0 + WIN_X1) / 2, 0.55]        # where the shop owner presses E
s["serviceSpot"] = [(WIN_X0 + WIN_X1) / 2, -0.9]     # where the client waits outside
s["serviceSign"] = [(WIN_X0 + WIN_X1) / 2, -0.32, WIN_Z1 + 0.13]
save("shops/standard.json", s)

u = load("upgrades/core.json")
for up in (u if isinstance(u, list) else u.get("upgrades", [])):
    if "bigger supplier stock" in up.get("description", ""):
        up["description"] = "Lv1: disassemble guns + rarer parts at the supplier. Lv2: 15% supplier discount, even rarer parts."
save("upgrades/core.json", u)
print("v4 content written")
