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
            self.gun.show() if armed else self.gun.hide()

    def remove(self):
        self.actor.cleanup()
        self.root.removeNode()


# ---------------------------------------------------------------------------- realistic humans (Universal Base Characters)
_human_cache = {}
_anim_np = None


def has_humans():
    return has("humans/male") and has("humans/anims")


def _anims():
    global _anim_np
    if _anim_np is None:
        _anim_np = _loader.loadModel(Filename.fromOsSpecific(_index["humans/anims"]))
    return _anim_np


def _outfit_texture(gender, skin, outfit):
    from panda3d.core import SamplerState
    key = ("tex", gender, skin, outfit)
    if key not in _human_cache:
        path = None
        for mod in os.listdir(os.path.join(ROOT, "mods")):
            p = os.path.join(ROOT, "mods", mod, "models", "textures", f"outfit_{gender}_{skin}_{outfit}.jpg")
            if os.path.isfile(p):
                path = p
        tex = _loader.loadTexture(Filename.fromOsSpecific(path)) if path else None
        if tex:
            tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
            tex.setAnisotropicDegree(4)
        _human_cache[key] = tex
    return _human_cache[key]


def _template(gender, skin, outfit):
    """Body + outfit texture + all animations, built once per look and copied for every character."""
    from panda3d.core import TextureAttrib
    key = (gender, skin, outfit)
    if key in _human_cache:
        return _human_cache[key]
    body = _loader.loadModel(Filename.fromOsSpecific(_index[f"humans/{gender}"])).copyTo(NodePath("t"))
    tex = _outfit_texture(gender, skin, outfit)
    if tex:
        for gnp in body.findAllMatches("**/+GeomNode"):
            for i in range(gnp.node().getNumGeoms()):
                ta = gnp.node().getGeomState(i).getAttrib(TextureAttrib)
                if not ta:
                    continue
                for st in ta.getOnStages():
                    t = ta.getOnTexture(st)
                    n = t.getName()
                    if "Superhero" in n and "Normal" not in n and "Roughness" not in n:
                        state = gnp.node().getGeomState(i).setAttrib(ta.addOnStage(st, tex))
                        gnp.node().setGeomState(i, state)
    for bn in _anims().findAllMatches("**/+AnimBundleNode"):
        bn.copyTo(body)
    _human_cache[key] = body
    return body


HAIR_M = ["hair_hair_simpleparted", "hair_hair_buzzed", "hair_hair_beard", None]
HAIR_F = ["hair_hair_long", "hair_hair_buns", "hair_hair_buzzedfemale"]
HAIR_COLORS = [(0.32, 0.22, 0.14, 1), (0.12, 0.1, 0.09, 1), (0.85, 0.7, 0.42, 1), (0.55, 0.26, 0.14, 1),
               (0.42, 0.3, 0.2, 1), (0.7, 0.68, 0.64, 1)]


class HumanChar:
    """Realistic animated person (players, townsfolk, vendors, zombies). Same interface as geom.Character."""

    def __init__(self, parent, look=0, outfit=None, zombie=False, scale=1.0, gender=None, skin=None):
        from direct.actor.Actor import Actor
        from panda3d.core import Mat4
        self.zombie = zombie
        gender = gender or ("female" if look % 3 == 1 else "male")
        skin = skin or ("dark" if (look // 2) % 2 else "light")
        outfit = outfit or (f"z{look % 3}" if zombie else f"c{look % 6}")
        self.root = parent.attachNewNode("human")
        self.actor = Actor(_template(gender, skin, outfit))
        self.actor.reparentTo(self.root)
        self.actor.setH(180)
        self.actor.setScale(scale)
        self.actor.makeSubpart("legs", ["pelvis"], ["spine_01"])
        self.actor.makeSubpart("upper", ["spine_01"])
        self.anims = set(self.actor.getAnimNames())
        self.cur = {"legs": None, "upper": None}
        self.dead = False
        self.flinch = 0.0
        self.special_until = 0.0
        hair = None if zombie and look % 2 else (HAIR_F if gender == "female" else HAIR_M)[look % (3 if gender == "female" else 4)]
        brows = "hair_eyebrows_female" if gender == "female" else "hair_eyebrows_regular"
        self.actor.update(force=True)
        self.head = self.actor.exposeJoint(None, "modelRoot", "Head")
        rest = Mat4(self.head.getMat(self.actor))
        rest.invertInPlace()
        hcol = HAIR_COLORS[(look * 7 + 3) % len(HAIR_COLORS)]
        for h in (hair, brows):
            if h and has("humans/" + h):
                hn = instance("humans/" + h, self.head)
                if hn is not None:
                    hn.setMat(rest)
                    hn.setColorScale(*((0.35, 0.34, 0.3, 1) if zombie else hcol))
        self.hand = self.actor.exposeJoint(None, "modelRoot", "hand_r")
        self.gun_mount = self.hand.attachNewNode("gunmount")
        self.gun_mount.setHpr(*HAND_HPR)
        self.gun_mount.setPos(*HAND_POS)
        self.gun = None
        self.gun_key = None
        self.muzzle = (0, 0.3, 0)

    def set_gun(self, loadout, parts):
        key = tuple(sorted(loadout.items()))
        if key == self.gun_key:
            return False
        if self.gun:
            self.gun.removeNode()
        from .geom import build_gun
        self.gun, self.muzzle = build_gun(self.gun_mount, loadout, parts)
        a0, b0 = self.gun.getTightBounds() or ((0, 0, 0), (0, 0.3, 0))
        info = None
        self.gun.setPos(0, -a0[1] - (b0[1] - a0[1]) * 0.28, -0.04)
        self.gun_key = key
        return True

    def muzzle_world(self, render):
        return render.getRelativePoint(self.gun, self.muzzle) if self.gun else self.root.getPos(render) + (0, 0, 1.4)

    def _play(self, part, name, rate=1.0, loop=True):
        if name not in self.anims:
            return
        if self.cur[part] != name:
            self.cur[part] = name
            if loop:
                self.actor.loop(name, partName=part)
            else:
                self.actor.play(name, partName=part)
        self.actor.setPlayRate(rate, name, partName=part)

    def gesture(self, name, seconds=1.6):
        import time
        if name in self.anims and not self.dead:
            self.special_until = time.monotonic() + seconds
            self.cur = {"legs": name, "upper": name}
            self.actor.play(name)

    def die(self):
        if not self.dead:
            self.dead = True
            if self.gun:
                self.gun.hide()
            self.cur = {"legs": "Death01", "upper": "Death01"}
            self.actor.play("Death01")

    def revive(self):
        if self.dead:
            self.dead = False
            if self.gun:
                self.gun.show()
            self.cur = {"legs": None, "upper": None}

    def animate(self, dt, speed, aim_pitch=0.0, armed=True):
        import time
        if self.dead:
            return
        if self.flinch > 0.55 and time.monotonic() > self.special_until:
            self.gesture("Hit_Chest", 0.35)
        self.flinch = max(0.0, self.flinch - dt * 4)
        if time.monotonic() < self.special_until:
            return
        if self.zombie:
            name = "Zombie_Walk_Fwd_Loop" if speed > 0.3 else "Zombie_Idle_Loop"
            rate = max(0.6, min(2.2, speed / 1.3)) if speed > 0.3 else 1.0
            self._play("legs", name, rate)
            self._play("upper", name, rate)
            return
        if speed > 5.0:
            legs, rate = "Sprint_Loop", min(1.4, speed / 6.5)
        elif speed > 2.2:
            legs, rate = "Jog_Fwd_Loop", min(1.5, speed / 3.8)
        elif speed > 0.3:
            legs, rate = "Walk_Loop", max(0.7, speed / 1.5)
        else:
            legs, rate = "Idle_Loop", 1.0
        self._play("legs", legs, rate)
        if self.gun:   # gun stays in the hand but always points where the character looks
            self.gun_mount.setHpr(self.root, 0, aim_pitch, 0)
        if armed and self.gun:
            self._play("upper", "Pistol_Aim_Neutral" if speed > 0.3 else "Pistol_Idle_Loop")
            self.gun.show()
        else:
            self._play("upper", legs, rate)
            if self.gun:
                self.gun.hide()

    def remove(self):
        self.actor.cleanup()
        self.root.removeNode()


HAND_POS = (0.0, 0.0, 0.0)
HAND_HPR = (0.0, 0.0, 0.0)
