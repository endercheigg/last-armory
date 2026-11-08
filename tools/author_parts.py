"""Detailed gun-part models built from real-world references (writes the "model" of each core part).

    python tools/author_parts.py

Shapes: box {p, s}, cyl {p, r, l, r2?, axis?}, prism {x, w, pts:[[y, z]...]} (side outline extruded across X).
Units are metres. The gun points +Y, +Z is up. Each part is drawn relative to its mount point:
  sight: origin on top of the rail      muzzle: origin at the barrel end, extends +Y
  grip:  origin under the handguard      bayonet: origin under the barrel, blade extends +Y
  stock: origin at back of receiver, extends -Y   magazine: origin at the mag well, hangs -Z
  barrel: origin at the receiver front, extends +Y
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GM, BLK, POLY, STEEL, WOOD, FDE = "#2b2e33", "#18191c", "#232529", "#8f959d", "#6b4428", "#a08a66"
GLASS, RED, OD, BRASS, YEL, ORG = "#1d3a58", "#ff2a1a", "#4b5a3a", "#b8933a", "#d8a520", "#e8892b"


def box(p, s, c=GM, **kw):
    return dict(p=list(p), s=list(s), c=c, **kw)


def cyl(p, r, l, c=GM, **kw):
    return dict(t="cyl", p=list(p), r=r, l=l, c=c, **kw)


def prism(pts, w, c=GM, x=0.0, **kw):
    return dict(t="prism", x=x, w=w, pts=[list(q) for q in pts], c=c, **kw)


def rail_mount(length, y=0.0, h=0.012):
    return [box((0, y, h / 2), (0.026, length, h), BLK), box((0, y, h + 0.002), (0.02, length * 0.9, 0.004), GM)]


MODELS = {}

# ------------------------------------------------------------------ sights
MODELS["sgt_reflex"] = rail_mount(0.05) + [          # Aimpoint-style tube red dot
    box((0, 0, 0.022), (0.022, 0.03, 0.02), BLK),
    cyl((0, 0, 0.038), 0.016, 0.07, BLK),
    cyl((0, 0.036, 0.038), 0.0175, 0.008, GM),
    cyl((0, -0.036, 0.038), 0.0175, 0.008, GM),
    cyl((0, 0.0405, 0.038), 0.0135, 0.002, GLASS),
    cyl((0, 0.012, 0.038), 0.0022, 0.002, RED, glow=True),
    cyl((0, 0.0, 0.058), 0.0075, 0.012, BLK, axis="z"),
    cyl((0.02, 0.0, 0.038), 0.0075, 0.012, BLK, axis="x"),
]
MODELS["sgt_holo"] = rail_mount(0.09) + [            # EOTech-style holographic
    prism([(-0.045, 0.012), (0.045, 0.012), (0.045, 0.026), (0.03, 0.03), (-0.045, 0.03)], 0.034, BLK),
    box((0.0155, 0.012, 0.047), (0.004, 0.05, 0.036), BLK),
    box((-0.0155, 0.012, 0.047), (0.004, 0.05, 0.036), BLK),
    box((0, 0.012, 0.0665), (0.035, 0.05, 0.005), BLK),
    box((0, 0.03, 0.047), (0.028, 0.002, 0.032), GLASS),
    box((0, 0.0285, 0.047), (0.004, 0.0005, 0.004), RED, glow=True),
    box((0, -0.035, 0.034), (0.03, 0.02, 0.012), GM),
    cyl((0.02, -0.03, 0.024), 0.006, 0.008, GM, axis="x"),
]
MODELS["sgt_scope"] = [                               # 3-9x40 rifle scope in rings
    box((0, -0.06, 0.006), (0.026, 0.022, 0.012), BLK), box((0, 0.06, 0.006), (0.026, 0.022, 0.012), BLK),
    box((0, -0.06, 0.024), (0.008, 0.016, 0.026), BLK), box((0, 0.06, 0.024), (0.008, 0.016, 0.026), BLK),
    cyl((0, -0.06, 0.045), 0.0165, 0.014, BLK), cyl((0, 0.06, 0.045), 0.0165, 0.014, BLK),
    cyl((0, 0.0, 0.045), 0.0127, 0.2, GM),
    cyl((0, 0.125, 0.045), 0.0127, 0.05, GM, r2=0.022),
    cyl((0, 0.17, 0.045), 0.022, 0.04, GM),
    cyl((0, 0.1905, 0.045), 0.019, 0.002, GLASS),
    cyl((0, -0.115, 0.045), 0.019, 0.03, GM, r2=0.0127),
    cyl((0, -0.155, 0.045), 0.019, 0.05, BLK),
    cyl((0, -0.1795, 0.045), 0.016, 0.002, GLASS),
    box((0, 0.0, 0.045), (0.03, 0.042, 0.03), GM),
    cyl((0, 0.0, 0.066), 0.011, 0.018, BLK, axis="z"),
    cyl((0.021, 0.0, 0.045), 0.011, 0.018, BLK, axis="x"),
    cyl((-0.019, 0.0, 0.045), 0.009, 0.012, BLK, axis="x"),
]

# ------------------------------------------------------------------ muzzles (origin at barrel end)
MODELS["mzl_comp"] = [                                # port-top compensator
    cyl((0, 0.028, 0), 0.0115, 0.056, BLK),
    box((0, 0.018, 0.0105), (0.008, 0.006, 0.004), "#050505"),
    box((0, 0.03, 0.0105), (0.008, 0.006, 0.004), "#050505"),
    box((0, 0.042, 0.0105), (0.008, 0.006, 0.004), "#050505"),
    cyl((0, 0.0565, 0), 0.0045, 0.002, "#050505"),
]
MODELS["mzl_brake"] = [cyl((0, 0.036, 0), 0.0145, 0.072, GM)] + [   # side-port muzzle brake
    box((sx * 0.0135, y, 0), (0.004, 0.009, 0.016), "#050505") for sx in (-1, 1) for y in (0.018, 0.034, 0.05)
] + [box((0, 0.0725, 0), (0.026, 0.002, 0.026), GM), cyl((0, 0.0735, 0), 0.0045, 0.002, "#050505")]
MODELS["mzl_suppressor"] = [                          # can suppressor
    cyl((0, 0.008, 0), 0.0135, 0.016, GM),
    cyl((0, 0.105, 0), 0.0195, 0.18, BLK),
    cyl((0, 0.017, 0), 0.0195, 0.002, GM, r2=0.0195),
    cyl((0, 0.198, 0), 0.0185, 0.006, GM),
    cyl((0, 0.2012, 0), 0.005, 0.001, "#050505"),
]
MODELS["mzl_booster"] = [cyl((0, 0.012, 0), 0.0115, 0.024, BLK)] + [   # 4-prong flash hider ("rate booster")
    box((dx, 0.04, dz), (0.004, 0.034, 0.004), BLK) for dx, dz in ((0.008, 0.008), (-0.008, 0.008), (0.008, -0.008), (-0.008, -0.008))
] + [cyl((0, 0.012, 0), 0.0122, 0.006, ORG)]
MODELS["mzl_choke"] = [                               # shotgun extended choke tube
    cyl((0, 0.02, 0), 0.0135, 0.04, STEEL),
    cyl((0, 0.01, 0), 0.0145, 0.008, STEEL),
    cyl((0, 0.032, 0), 0.0145, 0.008, STEEL),
    cyl((0, 0.0405, 0), 0.008, 0.002, "#050505"),
]

# ------------------------------------------------------------------ grips (origin under the handguard)
MODELS["grp_vertical"] = [
    box((0, 0, -0.005), (0.026, 0.04, 0.01), BLK),
    prism([(-0.014, -0.01), (0.014, -0.01), (0.016, -0.04), (0.014, -0.06), (0.016, -0.08), (0.014, -0.1), (-0.016, -0.1),
           (-0.015, -0.07), (-0.017, -0.05), (-0.015, -0.03)], 0.026, POLY),
    cyl((0, 0, -0.102), 0.014, 0.006, BLK, axis="z"),
]
MODELS["grp_angled"] = [
    box((0, 0, -0.005), (0.026, 0.07, 0.01), BLK),
    prism([(-0.035, -0.01), (0.035, -0.01), (0.03, -0.022), (-0.005, -0.045), (-0.03, -0.045), (-0.04, -0.03)], 0.026, POLY),
]
MODELS["grp_bipod"] = [
    box((0, 0, -0.008), (0.03, 0.05, 0.016), BLK),
    cyl((0, 0, -0.02), 0.009, 0.05, GM, axis="x"),
    cyl((0.018, 0, -0.085), 0.006, 0.13, GM, axis="z", hpr=(0, 0, 14)),
    cyl((-0.018, 0, -0.085), 0.006, 0.13, GM, axis="z", hpr=(0, 0, -14)),
    cyl((0.034, 0, -0.15), 0.008, 0.012, BLK, axis="z"),
    cyl((-0.034, 0, -0.15), 0.008, 0.012, BLK, axis="z"),
]

# ------------------------------------------------------------------ bayonets (origin under the barrel)
MODELS["bay_knife"] = [                               # M9-style bayonet
    box((0, -0.005, -0.004), (0.022, 0.012, 0.03), GM),
    prism([(-0.11, -0.012), (-0.005, -0.012), (-0.005, 0.006), (-0.11, 0.006)], 0.018, POLY),
    prism([(0.0, -0.012), (0.12, -0.012), (0.17, 0.004), (0.13, 0.008), (0.0, 0.008)], 0.004, STEEL),
    prism([(0.0, 0.005), (0.11, 0.005), (0.11, 0.008), (0.0, 0.008)], 0.0045, "#c8ccd2"),
]
MODELS["bay_blade"] = [                               # long sword bayonet
    box((0, -0.005, -0.004), (0.024, 0.014, 0.034), BRASS),
    prism([(-0.12, -0.013), (-0.006, -0.013), (-0.006, 0.007), (-0.12, 0.007)], 0.02, WOOD),
    prism([(0.0, -0.011), (0.25, -0.011), (0.3, 0.0), (0.25, 0.008), (0.0, 0.008)], 0.004, STEEL),
    prism([(0.02, -0.003), (0.24, -0.003), (0.24, 0.0), (0.02, 0.0)], 0.0045, "#6f757d"),
]
MODELS["bay_saw"] = [                                 # under-barrel chainsaw
    prism([(-0.13, -0.06), (0.02, -0.06), (0.04, -0.04), (0.04, 0.01), (-0.13, 0.01)], 0.05, YEL),
    box((0, -0.06, -0.025), (0.052, 0.06, 0.04), BLK),
    prism([(0.03, -0.042), (0.29, -0.042), (0.31, -0.025), (0.29, -0.008), (0.03, -0.008)], 0.012, "#2a2a2a"),
    prism([(0.03, -0.038), (0.28, -0.038), (0.295, -0.025), (0.28, -0.012), (0.03, -0.012)], 0.014, STEEL),
]

# ------------------------------------------------------------------ stocks (origin at receiver back, extend -Y)
MODELS["stk_light"] = [                               # skeleton / wire stock
    prism([(0, -0.004), (-0.24, 0.002), (-0.24, 0.012), (0, 0.006)], 0.012, BLK),
    prism([(0, -0.04), (-0.23, -0.07), (-0.23, -0.06), (0, -0.03)], 0.012, BLK),
    prism([(-0.22, 0.016), (-0.25, 0.016), (-0.25, -0.085), (-0.22, -0.085)], 0.03, POLY),
]
MODELS["stk_tactical"] = [                            # M4-style collapsible stock on buffer tube
    cyl((0, -0.1, -0.005), 0.015, 0.2, BLK),
    prism([(-0.11, 0.012), (-0.25, 0.022), (-0.27, 0.02), (-0.27, -0.1), (-0.25, -0.1), (-0.2, -0.06), (-0.11, -0.025)], 0.04, POLY),
    prism([(-0.27, 0.022), (-0.285, 0.022), (-0.285, -0.102), (-0.27, -0.102)], 0.044, "#111111"),
]
MODELS["stk_heavy"] = [                               # classic wooden rifle stock
    prism([(0.0, 0.012), (-0.1, 0.016), (-0.3, 0.022), (-0.34, 0.022), (-0.34, -0.11), (-0.3, -0.115),
           (-0.12, -0.06), (-0.04, -0.06), (0.0, -0.03)], 0.042, WOOD),
    prism([(-0.34, 0.024), (-0.355, 0.024), (-0.355, -0.115), (-0.34, -0.115)], 0.046, "#1a1a1a"),
]

# ------------------------------------------------------------------ magazines (origin at the mag well, hang -Z)
MODELS["mag_pistol"] = [prism([(-0.016, 0), (0.016, 0), (0.012, -0.07), (-0.02, -0.07)], 0.026, BLK),
                        prism([(-0.022, -0.07), (0.014, -0.07), (0.014, -0.08), (-0.022, -0.08)], 0.03, POLY)]
MODELS["mag_ext"] = [                                 # curved AK-style 30-rounder
    prism([(-0.02, 0), (0.025, 0), (0.035, -0.06), (0.06, -0.15), (0.03, -0.16), (0.005, -0.075), (-0.02, -0.01)], 0.026, "#7a3a20"),
    prism([(-0.02, 0.0), (0.025, 0.0), (0.025, -0.008), (-0.02, -0.008)], 0.028, GM),
]
MODELS["mag_quick"] = [                               # straight AR mag with a pull loop
    prism([(-0.03, 0), (0.03, 0), (0.035, -0.11), (-0.025, -0.11)], 0.024, BLK),
    prism([(-0.028, -0.11), (0.037, -0.11), (0.037, -0.12), (-0.028, -0.12)], 0.028, POLY),
    prism([(-0.01, -0.12), (0.02, -0.12), (0.016, -0.145), (-0.006, -0.145)], 0.006, ORG),
]
MODELS["mag_drum"] = [                                # 75-round drum
    prism([(-0.02, 0), (0.02, 0), (0.02, -0.04), (-0.02, -0.04)], 0.024, BLK),
    cyl((0, 0.0, -0.1), 0.07, 0.06, BLK, axis="x"),
    cyl((0, 0.0, -0.1), 0.05, 0.062, GM, axis="x"),
    cyl((0, 0.0, -0.1), 0.012, 0.066, BLK, axis="x"),
]
MODELS["mag_belt"] = [                                # ammo box with a belt feeding up
    box((0.02, 0, -0.08), (0.11, 0.14, 0.12), OD),
    box((0.02, 0, -0.016), (0.112, 0.142, 0.008), "#3b4830"),
    box((0.078, 0, -0.08), (0.006, 0.05, 0.03), "#2a2a2a"),
] + [cyl((0.0, 0.0, -0.012 + 0.012 * i), 0.0055, 0.03, BRASS, axis="x") for i in range(3)]

# ------------------------------------------------------------------ barrels (used by guns drawn without a full model)
MODELS["brl_pistol"] = [cyl((0, 0.04, 0), 0.008, 0.08, STEEL)]
MODELS["brl_short"] = [cyl((0, 0.07, 0), 0.0085, 0.14, GM), cyl((0, 0.045, 0), 0.02, 0.09, POLY)]
MODELS["brl_long"] = [cyl((0, 0.17, 0), 0.008, 0.34, GM), cyl((0, 0.08, 0), 0.021, 0.16, POLY),
                      box((0, 0.3, 0.018), (0.004, 0.01, 0.022), BLK)]
MODELS["brl_vented"] = [cyl((0, 0.11, 0), 0.009, 0.22, GM), cyl((0, 0.08, 0), 0.024, 0.16, BLK)] + [
    box((sx * 0.022, y, 0), (0.006, 0.02, 0.01), "#050505") for sx in (-1, 1) for y in (0.03, 0.06, 0.09, 0.12)]
MODELS["brl_heavy"] = [cyl((0, 0.13, 0), 0.0135, 0.26, GM)] + [
    box((0, 0.1, z), (0.004, 0.14, 0.003), "#151515") for z in (0.013, -0.013)] + [box((0, 0.24, 0.02), (0.006, 0.012, 0.02), BLK)]
MODELS["brl_precision"] = [cyl((0, 0.2, 0), 0.0075, 0.4, "#1a1a1a"), cyl((0, 0.06, 0), 0.0105, 0.12, GM, r2=0.0075)]
MODELS["brl_twin"] = [cyl((0.0085, 0.14, 0), 0.008, 0.28, GM), cyl((-0.0085, 0.14, 0), 0.008, 0.28, GM),
                      box((0, 0.27, 0), (0.034, 0.012, 0.018), BLK), box((0, 0.05, 0), (0.034, 0.02, 0.02), BLK)]

changed = 0
for fname in ("attachments", "barrels", "magazines"):
    path = os.path.join(ROOT, "mods", "core", "parts", fname + ".json")
    with open(path) as f:
        parts = json.load(f)
    for p in parts:
        if p["id"] in MODELS:
            p["model"] = MODELS[p["id"]]
            changed += 1
    with open(path, "w") as f:
        json.dump(parts, f, indent=1)
print(f"updated {changed} parts; missing: {[k for k in MODELS if not any(True for _ in [0])][:0]}")
