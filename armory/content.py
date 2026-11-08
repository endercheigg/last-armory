"""Loads every folder in /mods (see MODDING.md).

  mod.json, parts/, upgrades/, customers/, zombies/, towns/, shops/, arenas/, items/, patches.json, server.py
"""
import importlib.util
import json
import os

from .gun import SLOT_IDS, part_price

KINDS = ("parts", "upgrades", "customers", "zombies", "towns", "shops", "arenas", "items")


def _read(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Bad JSON in {path}: {e}") from None


def _files(folder):
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.endswith(".json")]


def load_content(mods_dir, disabled=(), load_scripts=True):
    out = {"mods": [], "hooks": [], "errors": []}
    for k in KINDS:
        out[k] = {}
    if not os.path.isdir(mods_dir):
        out["errors"].append(f"mods folder not found: {mods_dir}")
        return out
    metas = []
    for name in sorted(os.listdir(mods_dir)):
        d = os.path.join(mods_dir, name)
        mp = os.path.join(d, "mod.json")
        if not os.path.isfile(mp):
            continue
        try:
            meta = _read(mp)
        except ValueError as e:
            out["errors"].append(str(e))
            continue
        meta.setdefault("id", name)
        meta["dir"] = d
        meta.setdefault("loadOrder", 0 if meta["id"] == "core" else 100)
        if meta.get("enabled") is False or meta["id"] in disabled:
            continue
        metas.append(meta)
    metas.sort(key=lambda m: (m["loadOrder"], m["id"]))

    raw = {k: {} for k in KINDS}
    for meta in metas:
        try:
            for kind in KINDS:
                for path in _files(os.path.join(meta["dir"], kind)):
                    data = _read(path)
                    for item in data if isinstance(data, list) else [data]:
                        if "id" not in item:
                            item["id"] = os.path.splitext(os.path.basename(path))[0]
                        item["mod"] = meta["id"]
                        raw[kind][item["id"]] = item
            pp = os.path.join(meta["dir"], "patches.json")
            if os.path.isfile(pp):
                for iid, ch in _read(pp).items():
                    for kind in KINDS:
                        if iid in raw[kind]:
                            raw[kind][iid] = {**raw[kind][iid], **ch}
                            break
                    else:
                        out["errors"].append(f"{meta['id']}: patch for unknown id '{iid}'")
            script = os.path.join(meta["dir"], "server.py")
            if load_scripts and os.path.isfile(script):
                spec = importlib.util.spec_from_file_location(f"armory_mod_{meta['id']}", script)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod._mod_id = meta["id"]
                out["hooks"].append(mod)
            out["mods"].append({"id": meta["id"], "name": meta.get("name", meta["id"]),
                                "version": str(meta.get("version", "1.0")), "description": meta.get("description", "")})
        except Exception as e:
            out["errors"].append(f"{meta['id']}: {e}")

    def resolve(pid, seen):
        p = raw["parts"].get(pid)
        if p is None or "extends" not in p:
            return p
        if pid in seen:
            out["errors"].append(f"extends loop at '{pid}'")
            return p
        seen.add(pid)
        base = resolve(p["extends"], seen)
        if base is None:
            out["errors"].append(f"'{pid}' extends unknown part '{p['extends']}'")
            return p
        m = {**base, **p}
        for k in ("set", "add", "mul", "mounts"):
            m[k] = {**base.get(k, {}), **p.get(k, {})}
        m.pop("extends", None)
        return m

    for pid in raw["parts"]:
        p = resolve(pid, set())
        if p.get("hidden"):
            continue
        if p.get("slot") not in SLOT_IDS:
            out["errors"].append(f"part '{pid}' has unknown slot '{p.get('slot')}'")
            continue
        part = {
            "id": pid, "slot": p["slot"], "name": p.get("name", pid), "short": p.get("short", p.get("name", pid).split()[0]),
            "description": p.get("description", ""), "tier": max(0, min(4, p.get("tier", 0))),
            "set": p.get("set", {}), "add": p.get("add", {}), "mul": p.get("mul", {}),
            "length": p.get("length", 0.2), "mounts": p.get("mounts", {}), "model": p.get("model", []),
            "start": bool(p.get("start", False)), "mod": p["mod"],
            "meshes": p.get("meshes", []), "meshScale": p.get("meshScale", 1.0), "tint": p.get("tint"),
            "attachScale": p.get("attachScale", 1.0), "builtinSight": bool(p.get("builtinSight", False)),
        }
        part["price"] = p.get("price") or part_price(part)
        out["parts"][pid] = part
    for kind in KINDS[1:]:
        for iid, item in raw[kind].items():
            if not item.get("hidden"):
                out[kind][iid] = item
    return out


def client_payload(c):
    return {k: c[k] for k in ("parts", "upgrades", "customers", "zombies", "items", "mods")}
