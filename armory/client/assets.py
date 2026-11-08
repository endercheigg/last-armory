"""Model registry for the CC0 model packs in mods/*/models/ (converted to .bam by tools/convert_assets.py).

Everything falls back to the procedural box models when a model is missing, so servers can send content
that references models a player doesn't have.
"""
import json
import math
import os
import random

from panda3d.core import Filename, NodePath

ROOT = None
_index = {}      # "guns/Pistol_1" -> full path
_meta = {}       # "guns/Pistol_1" -> metadata from models.json
_static = {}     # cache of loaded static models
_loader = None

PLAYER_MODELS = ["chars/matt", "chars/lis", "chars/sam", "chars/shaun"]


def init(root, loader):
    """Scan every mod's models/ folder (later mods override earlier ones)."""
    global ROOT, _loader
    ROOT, _loader = root, loader
    _index.clear()
    _meta.clear()
    mods = os.path.join(root, "mods")
    if not os.path.isdir(mods):
        return
    for mod in sorted(os.listdir(mods), key=lambda m: (m != "core", m)):
        mdir = os.path.join(mods, mod, "models")
        if not os.path.isdir(mdir):
            continue
        mj = os.path.join(mdir, "models.json")
        if os.path.isfile(mj):
            try:
                with open(mj, encoding="utf-8") as f:
                    _meta.update(json.load(f).get("models", {}))
            except (OSError, ValueError):
                pass
        for base, _dirs, files in os.walk(mdir):
            for fn in files:
                stem, ext = os.path.splitext(fn)
                if ext.lower() in (".bam", ".egg", ".gltf", ".glb", ".obj"):
                    rel = os.path.relpath(os.path.join(base, stem), mdir).replace("\\", "/")
                    _index[rel] = os.path.join(base, fn)


def has(name):
    return name in _index


def meta(name):
    return _meta.get(name, {})


def instance(name, parent):
    """Static model copy under parent, or None."""
    path = _index.get(name)
    if not path or _loader is None:
        return None
    src = _static.get(name)
    if src is None:
        try:
            src = _loader.loadModel(Filename.fromOsSpecific(path))
        except Exception:
            src = None
        if src:
            from panda3d.core import SamplerState
            for tex in src.findAllTextures():
                tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
                tex.setAnisotropicDegree(8)
        _static[name] = src or False
    if not src:
        return None
    return src.copyTo(parent)


def fit(np, w, d, h):
    """Scale/center a model so it fills an axis-aligned box of size w x d x h (origin at the box's min corner)."""
    a, b = np.getTightBounds() or ((0, 0, 0), (1, 1, 1))
    sx, sy, sz = (b[0] - a[0]) or 1, (b[1] - a[1]) or 1, (b[2] - a[2]) or 1
    np.setScale(w / sx, d / sy, h / sz)
    np.setPos(-a[0] * w / sx, -a[1] * d / sy, -a[2] * h / sz)


# ---------------------------------------------------------------------------- guns
def gun_mesh_name(loadout, parts):
    rcv = parts.get(loadout.get("receiver", ""))
    meshes = [m for m in (rcv or {}).get("meshes", []) if has("guns/" + m) or has(m)]
    if not meshes:
        return None, rcv
    key = sum(ord(c) for k in ("barrel", "magazine", "stock") for c in loadout.get(k, ""))
    m = meshes[key % len(meshes)]
    return (m if has(m) else "guns/" + m), rcv


def build_gun_mesh(parent, loadout, parts, box_part_builder):
    """Real gun model for the receiver (variant picked by barrel/mag/stock) + small attachment models.
    Returns (root, muzzle) or None if no model is available."""
    name, rcv = gun_mesh_name(loadout, parts)
    if not name:
        return None
    root = parent.attachNewNode("gun")
    body = instance(name, root)
    if body is None:
        root.removeNode()
        return None
    info = meta(name)
    s = rcv.get("meshScale", 1.0)
    body.setScale(s)
    from .geom import hexc
    body.setColorScale(*(hexc(rcv["tint"]) if rcv.get("tint") else (0.5, 0.52, 0.56, 1)))
    muzzle = [v * s for v in info.get("muzzle", [0, 0.5, 0.02])]
    top = [v * s for v in info.get("top", [0, 0.2, 0.05])]
    under = [v * s for v in info.get("under", [0, 0.35, -0.03])]
    bay = [v * s for v in info.get("bayonet", [muzzle[0], muzzle[1] - 0.07, muzzle[2] - 0.022])]
    att = rcv.get("attachScale", 1.0)
    for slot, where in (("sight", top), ("muzzle", muzzle), ("grip", under), ("bayonet", bay)):
        if slot == "sight" and rcv.get("builtinSight"):
            continue   # this gun model already has its own scope
        p = parts.get(loadout.get(slot, ""))
        if p and p["slot"] == slot:
            node = box_part_builder(root, p)
            node.setPos(*where)
            node.setScale(att if slot != "muzzle" else max(att, 0.8))
    root.flattenStrong()
    return root, tuple(muzzle)


# ---------------------------------------------------------------------------- animated characters
class AnimChar:
    """Animated survivor / zombie (Quaternius). Same interface as geom.Character."""

    ARMED = {"idle": "Idle_Gun", "walk": "Walk_Gun", "run": "Run_Gun"}
    UNARMED = {"idle": "Idle", "walk": "Walk", "run": "Run"}
    ZOMBIE = {"idle": "Idle_Attack", "walk": "Walk", "run": "Run_Arms"}

    def __init__(self, parent, model, zombie=False, scale=1.0, tint=None):
        from direct.actor.Actor import Actor
        self.root = parent.attachNewNode("char")
        self.actor = Actor(Filename.fromOsSpecific(_index[model]))
        self.actor.reparentTo(self.root)
        self.actor.setH(meta(model).get("facing", 180))
        self.actor.setScale(scale)
        if tint:
            self.actor.setColorScale(*tint)
        self.zombie = zombie
        self.anims = set(self.actor.getAnimNames())
        self.current = None
        self.dead = False
        self.flinch = 0.0
        self.gun_mount = self.root.attachNewNode("gunmount")
        self.gun_mount.setPos(0.12, 0.42, 1.08)
        self.gun = None
        self.gun_key = None
        self.muzzle = (0, 0.3, 0)
        self.offset = random.uniform(0, 1)
        self.special_until = 0.0

    def set_gun(self, loadout, parts):
        key = tuple(sorted(loadout.items()))
        if key == self.gun_key:
            return False
        if self.gun:
            self.gun.removeNode()
        from .geom import build_gun
        self.gun, self.muzzle = build_gun(self.gun_mount, loadout, parts)
        a0, b0 = self.gun.getTightBounds() or ((0, 0, 0), (0, 0.3, 0))
        off = -a0[1] - (b0[1] - a0[1]) * 0.35
        self.gun.setPos(0, off, 0)
        self.gun_key = key
        return True

    def muzzle_world(self, render):
        return render.getRelativePoint(self.gun, self.muzzle) if self.gun else self.root.getPos(render)

    def play(self, name, loop=True, rate=1.0):
        if name not in self.anims:
            return
        if name != self.current:
            self.current = name
            if loop:
                self.actor.loop(name)
            else:
                self.actor.play(name)
        self.actor.setPlayRate(rate, name)

    def gesture(self, name, seconds=1.4):
        import time
        if name in self.anims:
            self.special_until = time.monotonic() + seconds
            self.current = name
            self.actor.play(name)

    def die(self):
        if not self.dead:
            self.dead = True
            if self.gun:
                self.gun.hide()
            self.current = "Death"
            self.actor.play("Death")

    def revive(self):
        if self.dead:
            self.dead = False
            if self.gun:
                self.gun.show()
            self.current = None

    def animate(self, dt, speed, aim_pitch=0.0, armed=True):
        import time
        if self.dead:
            return
        self.flinch = max(0.0, self.flinch - dt * 4)
        if time.monotonic() < self.special_until:
            return
        table = self.ZOMBIE if self.zombie else (self.ARMED if armed and self.gun else self.UNARMED)
        if speed > 4.2:
            self.play(table["run"], rate=min(1.6, speed / 5.5))
        elif speed > 0.3:
            self.play(table["walk"], rate=max(0.6, min(1.6, speed / 2.2)))
        else:
            self.play(table["idle"])
        if self.gun:
            self.gun_mount.setP(aim_pitch * 0.8)
            self.gun.show() if armed else self.gun.hide()

    def remove(self):
        self.actor.cleanup()
        self.root.removeNode()
