"""Guns: any part fits any gun. Stats = receiver 'set' -> all 'add' -> all 'mul' -> clamp."""

DEFAULTS = {
    "damage": 12.0, "fireRate": 4.0, "auto": 0, "pellets": 1, "spread": 2.5, "recoil": 0.6,
    "range": 40.0, "magSize": 10, "reloadTime": 1.6, "moveSpeed": 1.0, "headshot": 1.75,
    "zoom": 1.3, "explosionRadius": 0.0, "melee": 20.0,
}
LIMITS = {
    "damage": (1, 400), "fireRate": (0.3, 30), "pellets": (1, 20), "spread": (0, 30), "recoil": (0, 8),
    "range": (5, 200), "magSize": (1, 300), "reloadTime": (0.2, 8), "moveSpeed": (0.5, 1.8),
    "headshot": (1, 5), "zoom": (1, 8), "explosionRadius": (0, 12), "melee": (5, 200),
}
SLOTS = [
    {"id": "receiver", "name": "Receiver", "required": True},
    {"id": "barrel", "name": "Barrel", "required": True},
    {"id": "magazine", "name": "Magazine", "required": True},
    {"id": "stock", "name": "Stock", "required": False},
    {"id": "grip", "name": "Grip", "required": False},
    {"id": "sight", "name": "Scope", "required": False},
    {"id": "muzzle", "name": "Muzzle", "required": False},
    {"id": "bayonet", "name": "Bayonet", "required": False},
]
SLOT_IDS = [s["id"] for s in SLOTS]
RARITY = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
RARITY_COLORS = ["#b8bec8", "#5fd35f", "#3fa7ff", "#b46cff", "#ffc53f"]
TIER_PRICE = [20, 45, 90, 170, 320]


def part_price(part):
    return part.get("price") or TIER_PRICE[max(0, min(4, part.get("tier", 0)))]


def compute_stats(loadout, parts):
    s = dict(DEFAULTS)
    plist = [parts[pid] for pid in loadout.values() if pid in parts]
    plist.sort(key=lambda p: 0 if p["slot"] == "receiver" else 1)
    for p in plist:
        s.update(p["set"])
    for p in plist:
        for k, v in p["add"].items():
            s[k] = s.get(k, 0) + v
    for p in plist:
        for k, v in p["mul"].items():
            s[k] = s.get(k, 0) * v
    for k, (lo, hi) in LIMITS.items():
        s[k] = min(hi, max(lo, s[k]))
    s["pellets"] = int(round(s["pellets"]))
    s["magSize"] = int(round(s["magSize"]))
    s["dps"] = s["damage"] * s["pellets"] * s["fireRate"]
    return s


def gun_value(loadout, parts):
    """Base worth = what the parts cost, plus a small bonus for a complete, well-kitted gun."""
    total = sum(part_price(parts[pid]) for pid in loadout.values() if pid in parts)
    return round(total * (1.0 + 0.05 * max(0, len(loadout) - 3)))


def validate(loadout, parts):
    if not isinstance(loadout, dict):
        return "bad gun"
    for slot in SLOTS:
        pid = loadout.get(slot["id"])
        if not pid:
            if slot["required"]:
                return f"needs a {slot['name'].lower()}"
            continue
        p = parts.get(pid)
        if not p or p["slot"] != slot["id"]:
            return f"bad part {pid}"
    for k in loadout:
        if k not in SLOT_IDS:
            return f"unknown slot {k}"
    return None


def auto_name(loadout, parts, rng):
    rcv = parts.get(loadout.get("receiver", ""), {})
    adjectives = ["Rusty", "Grim", "Lucky", "Iron", "Last", "Quiet", "Mean", "Brutal", "Old", "Wasteland",
                  "Shiny", "Feral", "Holy", "Cursed", "Rapid", "Heavy", "Long", "Little"]
    nouns = {"receiver": rcv.get("short", rcv.get("name", "Gun").split()[0])}
    return f"{rng.choice(adjectives)} {nouns['receiver']}"
