"""Content for the survival update: Valorant-style guns, items, market stalls, bed/cleaning bench, bigger shops,
day/night colours, wasteland exits + loot spots.   python tools/author_survival.py   (safe to re-run)"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "mods", "core")


def load(rel):
    with open(os.path.join(CORE, rel)) as f:
        return json.load(f)


def save(rel, data):
    os.makedirs(os.path.dirname(os.path.join(CORE, rel)), exist_ok=True)
    with open(os.path.join(CORE, rel), "w") as f:
        json.dump(data, f, indent=1)


# ------------------------------------------------------------------ guns: Valorant-style numbers
# damage = body damage, headshot = head multiplier (legs are x0.85). 100 HP + up to 50 shields.
VAL = {
    "rcv_pistol":   dict(damage=26, headshot=3.0, fireRate=6.75, auto=0, magSize=12, reloadTime=1.75, spread=1.6, recoil=0.6, range=30),   # Classic: 78 head
    "rcv_smg":      dict(damage=26, headshot=3.0, fireRate=13.3, auto=1, magSize=30, reloadTime=2.25, spread=2.6, recoil=0.45, range=25),  # Spectre: 78 head
    "rcv_shotgun":  dict(damage=17, headshot=2.0, pellets=12, fireRate=3.5, auto=0, magSize=7, reloadTime=2.2, spread=10, recoil=2.5, range=12),  # Judge: body one-shot up close
    "rcv_rifle":    dict(damage=40, headshot=4.0, fireRate=9.75, auto=1, magSize=25, reloadTime=2.5, spread=1.2, recoil=0.55, range=50),  # Vandal: 160 head = one tap
    "rcv_marksman": dict(damage=65, headshot=3.0, fireRate=5.25, auto=0, magSize=12, reloadTime=2.5, spread=0.4, recoil=1.2, range=70),   # Guardian: 195 head
    "rcv_lmg":      dict(damage=38, headshot=2.5, fireRate=12, auto=1, magSize=100, reloadTime=5.0, spread=3.0, recoil=0.3, range=45, moveSpeed=0.85),  # Odin: 95 head
    "rcv_minigun":  dict(damage=28, headshot=2.4, fireRate=18, auto=1, magSize=150, reloadTime=5.5, spread=4.0, recoil=0.15, range=35, moveSpeed=0.78),
    "rcv_railgun":  dict(damage=150, headshot=1.7, fireRate=0.6, auto=0, magSize=5, reloadTime=3.7, spread=0.15, recoil=4, range=120),     # Operator: 255 head, 150 body
    "rcv_launcher": dict(damage=70, headshot=1.5, fireRate=1.0, auto=0, magSize=4, reloadTime=2.8, spread=1.5, recoil=2.5, range=50, explosionRadius=4),
}
rcv = load("parts/receivers.json")
for r in rcv:
    if r["id"] in VAL:
        zoom = r["set"].get("zoom", 1.3)
        r["set"] = dict(VAL[r["id"]], zoom=zoom)
    if r["id"] == "rcv_pistol":
        r["meshes"] = ["Pistol_1", "Pistol_2", "Pistol_3", "Pistol_4", "Pistol_5", "Pistol_6"]
        r["description"] = "Cheap sidearm. Three body shots or a head tap plus one."
if not any(r["id"] == "rcv_revolver" for r in rcv):
    base = next(r for r in rcv if r["id"] == "rcv_pistol")
    rev = json.loads(json.dumps(base))
    rev.update(id="rcv_revolver", name="Revolver Frame", short="Revolver", tier=1, start=False,
               description="Sheriff-style hand cannon: one shot to the head.",
               meshes=["Revolver_1", "Revolver_2", "Revolver_3", "Revolver_4", "Revolver_5"], attachScale=0.6,
               set=dict(damage=55, headshot=2.9, fireRate=4, auto=0, magSize=6, reloadTime=2.25, spread=0.9, recoil=2.2, range=45, zoom=1.4))
    rcv.insert(1, rev)
for r in rcv:
    head = r["set"]["damage"] * r["set"].get("headshot", 1.75)
    r["description"] = r["description"].split("  [")[0] + f"  [{r['set']['damage']} body / {head:.0f} head]"
save("parts/receivers.json", rcv)

# ------------------------------------------------------------------ items
save("items/core.json", [
    {"id": "jerky", "name": "Jerky", "kind": "food", "value": 20, "price": 8},
    {"id": "canned_food", "name": "Canned Beans", "kind": "food", "value": 35, "price": 12},
    {"id": "burger", "name": "Wasteland Burger", "kind": "food", "value": 70, "energy": 5, "price": 28},
    {"id": "coffee", "name": "Black Coffee", "kind": "drink", "value": 30, "price": 10},
    {"id": "energy_drink", "name": "Energy Drink", "kind": "drink", "value": 55, "hunger": 5, "price": 22},
    {"id": "bandage", "name": "Bandage", "kind": "heal", "value": 25, "price": 18},
    {"id": "medkit", "name": "Medkit", "kind": "heal", "value": 75, "price": 55},
    {"id": "light_shield", "name": "Light Shield (25)", "kind": "armor", "value": 25, "price": 60},
    {"id": "heavy_shield", "name": "Heavy Shield (50)", "kind": "armor", "value": 50, "price": 150},
    {"id": "cleaning_kit", "name": "Cleaning Kit", "kind": "tool", "value": 1, "price": 25},
])

# ------------------------------------------------------------------ upgrades: Night Armor -> Armor Locker
ups = load("upgrades/core.json")
for u in ups:
    if u["id"] == "armor":
        u["name"] = "Armor Locker"
        u["description"] = "Free shields every morning (25 / 35 / 50)."
        u["levels"] = [{"cost": 200, "effects": {"armorMorning": 25}}, {"cost": 450, "effects": {"armorMorning": 35}},
                       {"cost": 900, "effects": {"armorMorning": 50}}]
save("upgrades/core.json", ups)

# ------------------------------------------------------------------ shop template: taller, bed, cleaning bench
s = load("shops/standard.json")
if not s.get("v2"):
    H0, H1 = 3.4, 4.1
    nb = []
    for b in s["boxes"]:
        b = dict(b)
        if b.get("h") == H0:                 # walls
            b["h"] = H1
        if b.get("z") == H0:                 # roof
            b["z"] = H1
        if b.get("z") == 2.4 and b.get("x") == 5:   # door lintel -> wider, taller door
            b.update(x=4.7, w=2.6, z=2.9, h=H1 - 2.9)
        if b.get("y") == 0 and b.get("h") == H1 and b.get("x") == 0 and b.get("w") == 5:
            b["w"] = 4.7
        if b.get("y") == 0 and b.get("h") == H1 and b.get("x") == 7 and b.get("w") == 5:
            b.update(x=7.3, w=4.7)
        if b.get("x") == 11.55 and b.get("y") == 15.6:   # old upgrade board on the right wall -> move to the left wall
            b.update(x=0.3, y=17.4)
        nb.append(b)
    nb.append({"x": 10.4, "y": 14.6, "z": 0, "w": 1.25, "d": 2.3, "h": 0.55, "color": "#5a4a3a", "invisible": True})   # bed
    nb.append({"x": 0.35, "y": 14.9, "z": 0, "w": 1.3, "d": 1.6, "h": 0.9, "color": "#4a5058", "invisible": True})    # cleaning bench
    s["boxes"] = nb
    s["board"] = [0.5, 18.3]
    s["bed"] = [10.4, 15.75]
    s["clean"] = [1.4, 15.7]
    s["props"] += [
        {"mesh": "furniture/bedSingle", "x": 10.4, "y": 14.6, "z": 0, "h": 0},
        {"mesh": "furniture/desk", "x": 0.35, "y": 14.9, "z": 0, "h": 90, "tint": "#7a6a58"},
        {"mesh": "furniture/lampSquareTable", "x": 0.5, "y": 16.1, "z": 0.85},
    ]
    for lvl in s["decor"]:
        for b in lvl:
            if b.get("z") == 3.1:
                b["z"] = 3.75
    for lvl in s["sign"]:
        for b in lvl:
            b["z"] = b.get("z", 0) + 0.7
    for b in s.get("awning", []):
        b["z"] = b.get("z", 0) + 0.45
    s["signText"] = [6, -0.45, 4.55]
    for sh in s["shelves"]:
        sh[2] = 1.3
    for pr in s["props"]:
        if pr["mesh"] == "furniture/lampSquareCeiling":
            pr["z"] = 3.6
    s["v2"] = True
save("shops/standard.json", s)

# ------------------------------------------------------------------ town: market stalls + night colours
t = load("towns/haven.json")
t["vendors"] = [
    {"id": "food", "name": "Ma's Diner", "kind": "food", "x": 44, "y": 51.4, "h": 180, "color": "#c0392b",
     "items": ["jerky", "canned_food", "burger", "coffee", "energy_drink"]},
    {"id": "clinic", "name": "Field Clinic", "kind": "clinic", "x": 56, "y": 51.4, "h": 180, "color": "#e8e8e8",
     "items": ["bandage", "medkit"]},
    {"id": "utility", "name": "Ironside Supply", "kind": "utility", "x": 68, "y": 51.4, "h": 180, "color": "#2f6cb8",
     "items": ["light_shield", "heavy_shield", "cleaning_kit"]},
]
t["boxes"] = [b for b in t["boxes"] if not b.get("stall")]
for v in t["vendors"]:
    x = v["x"]
    t["boxes"] += [
        {"x": x - 1.7, "y": 52.0, "z": 0, "w": 3.4, "d": 0.7, "h": 1.0, "color": "#7a5634", "stall": True},
        {"x": x - 1.8, "y": 54.4, "z": 0, "w": 3.6, "d": 0.2, "h": 2.8, "color": "#6b5a48", "stall": True},
        {"x": x - 1.85, "y": 52.0, "z": 0, "w": 0.15, "d": 2.6, "h": 2.8, "color": "#5a4a3a", "stall": True},
        {"x": x + 1.7, "y": 52.0, "z": 0, "w": 0.15, "d": 2.6, "h": 2.8, "color": "#5a4a3a", "stall": True},
    ]
t["fence_h"] = 3.6
for b in t["boxes"]:
    if b.get("h") == 3 and b.get("color") == "#6f665a":
        b["h"] = 3.6
t["night"] = {"skyColor": "#0c1120", "fogColor": "#131a29", "ambient": "#3c4560", "lightColor": "#8fa4e0", "fogDensity": 0.016}
save("towns/haven.json", t)

# ------------------------------------------------------------------ wasteland: exits, loot, day colours
for name, exits, loot in (
        ("foundry", [[2.6, 2.6]], [[6, 20], [54, 20], [6, 40], [54, 40], [20, 6], [40, 6], [20, 54], [40, 54], [30, 36], [16, 30], [44, 30]]),
        ("shipyard", [[2.6, 2.6]], [[6, 16], [66, 16], [6, 36], [66, 36], [20, 6], [52, 6], [20, 46], [52, 46], [36, 30], [14, 26], [58, 26]])):
    a = load(f"arenas/{name}.json")
    night = {k: a[k] for k in ("skyColor", "fogColor", "ambient", "lightColor", "fogDensity") if k in a}
    a.setdefault("night", night)
    a["day"] = {"skyColor": "#9fb6cc", "fogColor": "#b3c2d0", "ambient": "#8a90a0", "lightColor": "#fff0d8", "fogDensity": 0.008}
    a["exits"] = exits
    a["entry"] = [[4.5, 4.5, 0, -45], [5.5, 3.5, 0, -40], [3.5, 5.5, 0, -50]]
    a["loot"] = loot
    a["name"] = {"foundry": "The Wasteland - Old Foundry", "shipyard": "The Wasteland - Dead Docks"}[name]
    save(f"arenas/{name}.json", a)
print("survival content written")
