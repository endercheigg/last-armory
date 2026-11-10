"""3D views: lobby, town (day, first person), night arena (PvP + zombies). Shared first-person base."""
import math
import random
import time

from panda3d.core import (CullFaceAttrib, RenderState, AmbientLight, Camera, DirectionalLight, Fog, KeyboardButton, MouseButton, NodePath,
                          PerspectiveLens, Point2, Point3, PointLight, Spotlight, TextureStage, TransparencyAttrib, Vec3)

from ..town import arena_boxes
from ..sim import EYE_H, SPRINT_MUL, aim_vec, box_tuple, move_player, ray_world
from . import hud as H
from . import assets as A
from . import materials as MAT
from .sky import Sky
from . import geom as G
from . import panels as P
from .geom import (PLAYER_COLORS, Character, box, box_min, build_gun, bounds_center, grid_texture, hexc, mix,
                   set_alpha, sphere_geom, text)

SEND_DT = 1 / 30
INTERP = 0.1


def key_down(app, *names):
    mw = app.mouseWatcherNode
    if not mw:
        return False
    alias = {"arrow_right": "right", "arrow_left": "left", "arrow_up": "up", "arrow_down": "down"}
    for n in names:
        n = alias.get(n, n)
        btn = KeyboardButton.asciiKey(n) if len(n) == 1 else getattr(KeyboardButton, n)()
        if mw.isButtonDown(btn):
            return True
    return False


def make_lights(root, sun_hex="#fff0dc", amb_hex="#5a6070", film=80, shadows=True):
    shadows = shadows and G.FANCY
    amb = AmbientLight("amb")
    amb.setColor(hexc(amb_hex))
    amb_np = root.attachNewNode(amb)
    sun = DirectionalLight("sun")
    c = hexc(sun_hex)
    sun.setColor((c[0] * 1.1, c[1] * 1.1, c[2] * 1.1, 1))
    if shadows:
        res = 4096 if film > 60 else 2048
        sun.setShadowCaster(True, res, res)
        sun.getLens().setFilmSize(film, film)
        sun.getLens().setNearFar(-120, 120)
        # render back faces into the shadow map: removes the striped "shadow acne" on lit surfaces
        sun.setInitialState(RenderState.make(CullFaceAttrib.makeReverse()))
    sun_np = root.attachNewNode(sun)
    sun_np.setHpr(35, -55, 0)
    root.setLight(amb_np)
    root.setLight(sun_np)
    return sun_np, amb_np


class Effects:
    """Tracers, sparks, explosions, floating texts - owned by a view."""

    def __init__(self, root, render):
        self.root = root
        self.render = render
        self.items = []

    def tracer(self, a, b, color=(1, 0.9, 0.5, 1), width=0.035, life=0.07):
        a, b = Vec3(*a), Vec3(*b)
        d = b - a
        L = d.length()
        if L < 0.05:
            return
        np = box(self.root, (0, 0, 0), (width, L, width), color)
        np.setPos(a + d * 0.5)
        np.lookAt(np.getPos() + d)
        np.setLightOff()
        np.setTransparency(TransparencyAttrib.MAlpha)
        self.items.append({"np": np, "t": 0, "life": life, "kind": "fade"})

    def sparks(self, p, color=(1, 0.8, 0.4, 1), n=5, speed=4):
        for _ in range(n):
            np = box(self.root, p, (0.05, 0.05, 0.05), color)
            np.setLightOff()
            v = Vec3(random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0, 1.2))
            v.normalize()
            self.items.append({"np": np, "t": 0, "life": random.uniform(0.15, 0.3), "kind": "spark", "v": v * speed})

    def flash(self, p, size=0.25, color=(1, 0.85, 0.4, 1)):
        np = sphere_geom().copyTo(self.root)
        np.setPos(*p)
        np.setScale(size)
        np.setColor(*color)
        np.setLightOff()
        np.setTransparency(TransparencyAttrib.MAlpha)
        self.items.append({"np": np, "t": 0, "life": 0.05, "kind": "fade"})

    def boom(self, p, r):
        np = sphere_geom().copyTo(self.root)
        np.setPos(*p)
        np.setColor(1, 0.55, 0.15, 1)
        np.setLightOff()
        np.setTransparency(TransparencyAttrib.MAlpha)
        self.items.append({"np": np, "t": 0, "life": 0.5, "kind": "boom", "r": r})
        self.sparks(p, (1, 0.6, 0.2, 1), 14, 9)

    def float_text(self, parent, s, color, z=2.6, font=None, scale=0.45):
        np = text(parent, s, scale, color, font=font)
        np.setZ(z)
        np.setBillboardPointEye()
        self.items.append({"np": np, "t": 0, "life": 1.4, "kind": "rise"})

    def update(self, dt):
        keep = []
        for it in self.items:
            it["t"] += dt
            k = it["t"] / it["life"]
            np = it["np"]
            if k >= 1:
                np.removeNode()
                continue
            if it["kind"] == "fade":
                np.setAlphaScale(1 - k)
            elif it["kind"] == "spark":
                it["v"].z -= 12 * dt
                np.setPos(np.getPos() + it["v"] * dt)
            elif it["kind"] == "boom":
                np.setScale(it["r"] * (0.3 + 0.7 * k))
                np.setAlphaScale(0.85 * (1 - k))
            elif it["kind"] == "rise":
                np.setZ(np.getZ() + dt * 1.2)
                np.setAlphaScale(1 - max(0, k - 0.6) / 0.4)
            keep.append(it)
        self.items = keep

    def clear(self):
        for it in self.items:
            it["np"].removeNode()
        self.items = []




# ====================================================================== MODELS IN THE WORLD
def place_prop(parent, pr):
    """A prop: {"mesh", "x", "y", "z", "h", "s"}. Returns the node or None if the model is missing."""
    n = parent.attachNewNode("prop")
    inst = A.instance(pr["mesh"], n)
    if inst is None:
        n.removeNode()
        return None
    n.setPos(pr["x"], pr["y"], pr.get("z", 0))
    n.setH(pr.get("h", 0))
    n.setScale(pr.get("s", 1.0))
    if pr.get("tint"):
        n.setColorScale(*hexc(pr["tint"]))
    return n


def place_box(parent, b, cube_parent=None):
    """A collision box drawn as a cube, or as a real model stretched to fill it ("mesh"), or not at all ("invisible")."""
    if b.get("invisible"):
        return None
    if b.get("mesh") and A.has(b["mesh"]):
        n = parent.attachNewNode("meshbox")
        n.setPos(b["x"], b["y"], b.get("z", 0))
        holder = n.attachNewNode("h")
        inst = A.instance(b["mesh"], holder)
        a0, b0 = inst.getTightBounds()
        if (b["w"] < b["d"]) != ((b0[0] - a0[0]) < (b0[1] - a0[1])):
            inst.setH(90)
        A.fit(holder, b["w"], b["d"], b["h"])
        if b.get("tint"):
            n.setColorScale(*hexc(b["tint"]))
        return n
    return box_min(cube_parent or parent, b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"], hexc(b.get("color", "#6b6f75")))


# ====================================================================== CHARACTER FACTORIES
def make_player(parent, info, gun_scale=1.15):
    if A.has_humans():
        c = info["color"] % 8
        return A.HumanChar(parent, look=info["id"] * 5 + c, outfit=f"p{c}", gender="female" if info["id"] % 3 == 2 else "male")
    if A.has(A.PLAYER_MODELS[0]):
        return A.AnimChar(parent, A.PLAYER_MODELS[info["color"] % len(A.PLAYER_MODELS)])
    return Character(parent, PLAYER_COLORS[info["color"] % 8], gun_scale=gun_scale)


def make_customer(parent, look):
    if A.has_humans():
        return A.HumanChar(parent, look=look)
    if A.has(A.PLAYER_MODELS[0]):
        f = 0.8 + (look * 37 % 40) / 100.0
        return A.AnimChar(parent, A.PLAYER_MODELS[look % len(A.PLAYER_MODELS)], tint=(f, f * 0.97, f * 0.94, 1))
    return Character(parent, CIVILIAN[look % len(CIVILIAN)], gun_scale=1, pants_hex=CIVILIAN[(look + 3) % len(CIVILIAN)],
                     hat=look % 3 == 0)


def make_zombie(parent, zt, look=0):
    if A.has_humans():
        return A.HumanChar(parent, look=look, zombie=True, scale=zt.get("scale", 1.0))
    mesh = zt.get("mesh", "zombies/basic")
    if A.has(mesh):
        return A.AnimChar(parent, mesh, zombie=True, scale=zt.get("scale", 1.0))
    ch = Character(parent, "#5a5040", skin_hex=zt.get("color", "#6b8f4e"), zombie=True, pants_hex="#3a3328", hat=False)
    ch.root.setScale(zt.get("scale", 1.0))
    return ch


CIVILIAN = ["#b55d3c", "#4f7a9a", "#7a6a4f", "#5f8a5a", "#8a4f6a", "#a08a3c", "#4f5a8a", "#8a8a8a"]


# ====================================================================== LOBBY
class LobbyView:
    def __init__(self, m):
        self.m = m
        self.root = m.world.attachNewNode("lobby")
        app = m.app
        app.setBackgroundColor(*hexc("#141820"))
        app.render.clearFog()
        sun, _ = make_lights(self.root, "#fff4e4", "#9aa0b0", film=30)
        sun.setHpr(200, -40, 0)  # light the characters from the camera side
        m.hud.show_combat(False)
        box(self.root, (0, 0, -0.1), (40, 40, 0.2), hexc("#2a2e36"))
        box(self.root, (0, 0, 0.05), (14, 4, 0.1), hexc("#3a3f48"))
        self.chars = {}
        self.t = 0
        self.key = None

    def refresh(self):
        key = tuple(sorted((p["id"], tuple(sorted(p["held"].items()))) for p in self.m.infos.values()))
        if key == self.key:
            return
        self.key = key
        for c in self.chars.values():
            c.remove()
        self.chars = {}
        ps = sorted(self.m.infos.values(), key=lambda p: p["id"])
        n = len(ps)
        for i, p in enumerate(ps):
            c = make_player(self.root, p, gun_scale=1.8)
            c.root.setPos((i - (n - 1) / 2) * 1.6, 0, 0.1)
            c.root.setH(180)
            c.set_gun(p["held"], self.m.parts)
            tag = text(c.root, p["name"], 0.2, hexc(PLAYER_COLORS[p["color"] % 8]), font=self.m.app.font3d)
            tag.setZ(2.15)
            tag.setBillboardPointEye()
            self.chars[p["id"]] = c

    def update(self, dt):
        self.refresh()
        self.t += dt
        cam = self.m.app.camera
        a = math.sin(self.t * 0.25) * 0.35
        cam.setPos(math.sin(a) * 9, -math.cos(a) * 9, 2.6)
        cam.lookAt(0, 0, 1.1)
        for c in self.chars.values():
            c.animate(dt, 0)

    def destroy(self):
        self.root.removeNode()


# ====================================================================== FIRST-PERSON BASE
class FPSView:
    night = False

    def __init__(self, m, boxes, size, light, ambient, sky, fog_color, fog_density, ground_color, ground_extra=60, props=(),
                 ground_mat="concrete"):
        self.m = m
        app = m.app
        self.size = size
        self.boxes = [box_tuple(b) for b in boxes]
        self.root = m.world.attachNewNode("view")
        self.static = self.root.attachNewNode("static")
        self.fx = Effects(self.root, app.render)
        self.font = app.font3d
        app.setBackgroundColor(*hexc(sky))
        fog = Fog("fog")
        fog.setColor(*hexc(fog_color)[:3])
        fog.setExpDensity(fog_density)
        app.render.setFog(fog)
        W, D = size
        self.sun, self.amb = make_lights(self.root, light, ambient, film=min(90, max(W, D) * 1.2))
        self.sun.setPos(W / 2, D / 2, 0)
        mats = MAT.Builder(self.static)
        ge = ground_extra
        if not mats.add(-ge, -ge, -0.5, W + ge * 2, D + ge * 2, 0.5, ground_mat, MAT.tint_for({"color": ground_color})):
            g = box(self.static, (W / 2, D / 2, -0.25), (W + ge * 2, D + ge * 2, 0.5), hexc(ground_color))
            g.setTexture(grid_texture(cells=2, line=0.9))
            g.setTexScale(TextureStage.getDefault(), (W + ge * 2) / 4, (D + ge * 2) / 4)
        blocks = self.static.attachNewNode("blocks")
        models = self.root.attachNewNode("models")  # not flattened: keeps per-model tints
        for b in boxes:
            if not b.get("invisible") and not (b.get("mesh") and A.has(b["mesh"])) and mats.add_box(b):
                continue
            place_box(models, b, blocks)
        mats.finish()
        blocks.setTexture(grid_texture(line=0.9, cells=2))
        for pr in props:
            place_prop(models, pr)
        self.blocks = blocks
        self.chars = {}
        self.dead_at = {}
        self.snaps = []
        self.pred = None
        self.render_pos = None
        self.pending = []
        self.seq = 0
        self.send_acc = 0.0
        self.clicks = 0
        self.melees = 0
        self.h = 0.0
        self.p = 0.0
        self.me_state = {"ammo": 0, "reload": 0, "ack": 0, "spd": 7, "vz": 0, "gr": 1}
        self.was_reloading = False
        self.ads = 0.0
        self.kick = 0.0
        self.stab = 0.0
        self.bob = 0.0
        self.mouse_was_down = False
        self.f_was_down = False
        self.start_at = 0.0
        # viewmodel in its own display region (never clips into walls)
        self.vm_root = NodePath("vm")
        G.shader_auto(self.vm_root)
        self.dr = app.win.makeDisplayRegion()
        self.dr.setSort(5)
        self.dr.setClearDepthActive(True)
        lens = PerspectiveLens()
        lens.setFov(62)
        lens.setNear(0.01)
        lens.setFar(20)
        self.vm_lens = lens
        self.vm_cam = self.vm_root.attachNewNode(Camera("vmcam", lens))
        self.dr.setCamera(self.vm_cam)
        make_lights(self.vm_root, light, "#8a90a0", shadows=False)
        self.vm_holder = self.vm_root.attachNewNode("holder")
        self.vm_gun = None
        self.vm_key = None
        self.vm_muzzle = (0, 0.3, 0)
        self.vm_flash = None
        self.vm_flash_t = 0.0
        self.fog = fog
        self.palettes = {}
        self.night_on = None
        self.env_key = None
        self.sky = Sky(app)
        self.sprint = 0.0
        self.step_t = 0.0
        torch = Spotlight("torch")
        torch.setColor((1.4, 1.3, 1.1, 1))
        torch.getLens().setFov(44)
        torch.getLens().setNearFar(0.3, 45)
        torch.setAttenuation((1, 0.035, 0.003))
        self.torch = app.render.attachNewNode(torch)
        self.objects = []
        self.prompt_obj = None
        app.camLens.setNearFar(0.05, 450)  # a sane depth range stops distant surfaces flickering

    def set_palettes(self, day, night):
        self.palettes = {"day": day, "night": night}

    BLOOD = {"skyColor": "#2a0606", "fogColor": "#3a0b0b", "ambient": "#5a2a2a", "lightColor": "#ff6a4a", "fogDensity": 0.02}

    def night_amount(self):
        """0 by day, 1 at night, easing through dusk (end of the day) and dawn (start of the day)."""
        m = self.m
        dm, nm = m.server.get("dayMinutes", 6), m.server.get("nightMinutes", 3)
        dfrac = dm / float(dm + nm)
        tod = m.tod
        w = min(0.06, dfrac * 0.25)
        ease = lambda x: x * x * (3 - 2 * x)
        if tod < w:
            return 1 - ease(tod / w), 0.0
        if tod < dfrac - w:
            return 0.0, tod / dfrac
        if tod < dfrac:
            return ease((tod - (dfrac - w)) / w), tod / dfrac
        return 1.0, 1.0

    def update_env(self):
        """Blend sky, fog, sun and ambient light for the time of day; the sun crosses the sky and sets."""
        m = self.m
        app = m.app
        a, u = self.night_amount()
        key = (round(a, 3), round(u, 3), bool(m.blood))
        if key == self.env_key:
            return
        self.env_key = key
        day = self.palettes.get("day") or {}
        night = dict(self.palettes.get("night") or {})
        if m.blood:
            night.update(self.BLOOD)

        def col(pal, k, default):
            return hexc(pal.get(k, default))[:3]

        def mixc(c0, c1, t):
            return tuple(c0[i] + (c1[i] - c0[i]) * t for i in range(3))
        sky = mixc(col(day, "skyColor", "#a9c3d9"), col(night, "skyColor", "#0c1120"), a)
        fogc = mixc(col(day, "fogColor", day.get("skyColor", "#b9c9d6")), col(night, "fogColor", "#131a29"), a)
        amb = mixc(col(day, "ambient", "#8a90a0"), col(night, "ambient", "#3c4560"), a)
        l0, l1 = col(day, "lightColor", "#fff2dc"), col(night, "lightColor", "#8fa4e0")
        light = mixc(tuple(c * 1.1 for c in l0), (l1[0] * 0.5, l1[1] * 0.5, l1[2] * 0.6), a)
        dens = day.get("fogDensity", 0.006) * (1 - a) + night.get("fogDensity", 0.016) * a
        glow = 4 * a * (1 - a)                    # peaks in the middle of sunset / sunrise
        fogc = mixc(fogc, (0.96, 0.56, 0.32), glow * 0.55)
        light = mixc(light, (1.0, 0.62, 0.36), glow * 0.5)
        light = tuple(c * (1 - 0.45 * glow) for c in light)
        zen = (sky[0] * 0.55, sky[1] * 0.72, sky[2])
        app.setBackgroundColor(fogc[0], fogc[1], fogc[2], 1)
        self.fog.setColor(*fogc)
        self.fog.setExpDensity(dens)
        self.amb.node().setColor((amb[0], amb[1], amb[2], 1))
        self.sun.node().setColor((light[0], light[1], light[2], 1))
        el, az = 14 + 52 * math.sin(math.pi * u), 120 - 150 * u
        mel, maz = 48.0, -50.0

        def toward(azd, eld):
            r, e = math.radians(azd), math.radians(eld)
            return (math.sin(r) * math.cos(e), -math.cos(r) * math.cos(e), math.sin(e))
        if a < 0.5:
            self.sun.setHpr(az, -el, 0)
        else:
            self.sun.setHpr(maz, -mel, 0)
        self.sky.set(zen, fogc, toward(az, el), 1 - a, toward(maz, mel), a, a * (0.3 if m.blood else 1.0),
                     moon_color=(1.0, 0.3, 0.22) if m.blood else (0.9, 0.92, 1.0))
        dark = a > 0.5
        if dark != self.night_on:
            self.night_on = dark
            if dark:
                self.root.setLight(self.torch)
            else:
                self.root.clearLight(self.torch)

    # -------------------------------------------------- waypoint markers
    def marker_list(self):
        """[(world pos, label, colour)] - subclasses say what is worth pointing at."""
        return []

    def update_markers(self):
        m = self.m
        app = m.app
        out = []
        if self.render_pos is not None and self.alive() and m.panel is None:
            a = app.getAspectRatio()
            eye = app.camera.getPos(app.render)
            for pos, label, color in self.marker_list()[:6]:
                wp = Point3(pos[0], pos[1], pos[2] if len(pos) > 2 else 1.5)
                dist = (wp - eye).length()
                if dist < 3.5:
                    continue
                p = app.cam.getRelativePoint(app.render, wp)
                p2 = Point2()
                if p.y > 0.1 and app.camLens.project(p, p2) and abs(p2.x) < 0.92 and abs(p2.y) < 0.84:
                    out.append((p2.x * a, p2.y + 0.04, f"{label}  {dist:.0f}m", color))
                    continue
                dx, dz = p.x, p.z * (0.25 if p.y <= 0.1 else 1.0)      # behind you: mostly say left or right
                L = math.hypot(dx, dz) or 1.0
                ex, ez = dx / L, dz / L
                k = min((a - 0.42) / max(1e-3, abs(ex)), 0.8 / max(1e-3, abs(ez)))
                arrow = f"{label}  {dist:.0f}m >" if ex > 0.3 else (f"< {label}  {dist:.0f}m" if ex < -0.3 else f"{label}  {dist:.0f}m")
                out.append((ex * k, ez * k, arrow, color))
        m.hud.set_markers(out)

    # -------------------------------------------------- interaction (objects with a "pos", described by subclasses)
    def find_object(self):
        cam = self.m.app.camera
        render = self.m.app.render
        eye = cam.getPos(render)
        fwd = render.getRelativeVector(cam, Vec3(0, 1, 0))
        best, best_score = None, None
        for o in self.objects:
            pp = Vec3(*o["pos"])
            d = pp - eye
            dist = d.length()
            if dist > o.get("range", 2.8) or dist < 1e-3:
                continue
            cosang = d.dot(fwd) / dist
            if cosang < (0.6 if o.get("range", 2.8) > 3 else 0.88):
                continue
            score = dist * (2 - cosang)
            if best is None or score < best_score:
                best, best_score = o, score
        return best

    def describe(self, o):
        return None, False

    def interact(self):
        pass

    def update_prompt(self):
        m = self.m
        self.prompt_obj = None
        if self.controls_enabled():
            o = self.find_object()
            label, ok = self.describe(o) if o else (None, False)
            if ok:
                self.prompt_obj = o
            m.hud.prompt.setText(label or "")
        else:
            m.hud.prompt.setText("")

    # -------------------------------------------------- state
    def teleport(self, m):
        self.pred = {"x": float(m["x"]), "y": float(m["y"]), "z": float(m["z"]), "vz": 0.0, "ground": False}
        self.render_pos = Vec3(self.pred["x"], self.pred["y"], self.pred["z"])
        self.pending = []
        if "h" in m:
            self.h = float(m["h"])
            self.p = 0.0

    def my_row(self):
        return self.snaps[-1][1].get(self.m.me) if self.snaps else None

    def alive(self):
        r = self.my_row()
        return bool(r and r[7])

    def on_snapshot(self, msg):
        self.snaps.append((time.monotonic(), {r[0]: r for r in msg["p"]}))
        self.snaps = self.snaps[-30:]
        me = msg.get("me")
        if me:
            self.me_state = me
            if me["reload"] > 0 and not self.was_reloading:
                self.m.app.sounds.play("reload", 0.7)
            self.was_reloading = me["reload"] > 0
            r = self.snaps[-1][1].get(self.m.me)
            if r and r[7]:
                self.reconcile(r, me)

    def reconcile(self, r, me):
        ack = me["ack"]
        self.pending = [p for p in self.pending if p[0] > ack]
        s = {"x": r[1], "y": r[2], "z": r[3], "vz": me["vz"], "ground": bool(me["gr"])}
        for _, mf, ms, j, h, sp in self.pending:
            move_player(s, mf, ms, j, h, me["spd"] * (SPRINT_MUL if sp else 1.0), SEND_DT, self.boxes, self.size)
        if self.pred is None:
            self.render_pos = Vec3(s["x"], s["y"], s["z"])
        self.pred = s

    def dist_vol(self, p):
        cam = self.m.app.camera.getPos(self.m.app.render)
        return max(0.06, 1 - (cam - p).length() / 70)

    def on_shot(self, msg):
        m = self.m
        pid = msg["p"]
        st = m.stats(pid)
        render = m.app.render
        if pid == m.me and self.alive():
            start = render.getRelativePoint(m.app.camera, Point3(0.12, 1.6, -0.12))
            self.kick = min(1.5, self.kick + 0.5 + (st["recoil"] if st else 1) * 0.15)
            if self.vm_flash:
                self.vm_flash.show()
                self.vm_flash_t = 0.05
            vol = 0.85
        else:
            c = self.chars.get(pid)
            start = c.muzzle_world(render) if c else Point3(*msg["o"])
            self.fx.flash(start, 0.15)
            vol = self.dist_vol(start)
        m.app.sounds.shot(st, vol)
        rail = st and st["damage"] >= 80
        for x, y, z, kind in msg["e"]:
            end = Point3(x, y, z)
            self.fx.tracer(start, end, (0.4, 0.9, 1, 1) if rail else (1, 0.9, 0.55, 1), 0.07 if rail else 0.03, 0.3 if rail else 0.07)
            if kind == 0:
                self.fx.sparks(end, (1, 0.8, 0.4, 1), 3, 3)
            elif kind in (1, 2):
                self.fx.sparks(end, (0.85, 0.1, 0.1, 1), 5, 3)
            elif kind == 3:
                self.fx.sparks(end, (1, 1, 1, 1), 4, 2)

    def on_melee(self, msg):
        if msg["p"] == self.m.me:
            self.stab = 1.0
            self.m.app.sounds.play("stab", 0.7)

    def on_boom(self, msg):
        p = Point3(msg["x"], msg["y"], msg["z"])
        self.fx.boom(p, msg["r"])
        self.m.app.sounds.play("boom", self.dist_vol(p))

    def on_damage(self, msg):
        c = self.chars.get(msg["v"])
        if c:
            c.flinch = 0.6
            if msg.get("a") == self.m.me:
                self.fx.float_text(c.root, str(msg["n"]), H.BAD if msg.get("hd") else H.WHITE, z=2.3, font=self.font, scale=0.3)

    def interp_rows(self, key, idx_alive=None):
        """Interpolate rows of the snapshot list stored under `key` ('p' handled by self.snaps)."""
        now = time.monotonic() - INTERP
        s = self.snaps
        if not s:
            return {}
        if len(s) == 1 or now <= s[0][0]:
            return {k: list(v) + [0] for k, v in s[0][1].items()}
        for i in range(len(s) - 1, 0, -1):
            t0, f0 = s[i - 1]
            t1, f1 = s[i]
            if t0 <= now:
                k = 1.0 if t1 == t0 else min(1.0, (now - t0) / (t1 - t0))
                out = {}
                for pid, r1 in f1.items():
                    r0 = f0.get(pid)
                    if r0 and r0[7] and r1[7]:
                        dh = (r1[4] - r0[4] + 180) % 360 - 180
                        out[pid] = [pid, r0[1] + (r1[1] - r0[1]) * k, r0[2] + (r1[2] - r0[2]) * k, r0[3] + (r1[3] - r0[3]) * k,
                                    r0[4] + dh * k, r0[5] + (r1[5] - r0[5]) * k, r1[6], r1[7],
                                    math.hypot(r1[1] - r0[1], r1[2] - r0[2]) / max(1e-3, t1 - t0)]
                    else:
                        out[pid] = list(r1) + [0]
                return out
        return {k: list(v) + [0] for k, v in s[-1][1].items()}

    # -------------------------------------------------- frame
    def controls_enabled(self):
        m = self.m
        return (self.alive() and not m.menu_open and not m.chat_open and m.panel is None and not self.me_state.get("sl")
                and self.m.app.mouseWatcherNode is not None)

    def update(self, dt):
        m = self.m
        app = m.app
        now = time.monotonic()
        frozen = now < self.start_at
        alive = self.alive()
        st = m.stats(m.me)
        controlling = self.controls_enabled()
        m.set_capture(controlling)
        if controlling:
            dx, dy = m.mouse_delta()
            sens = app.settings["sens"] / (1 + ((st["zoom"] if st else 1.3) - 1) * self.ads)
            self.h -= dx * sens
            self.p = max(-88, min(88, self.p - dy * sens))
        mf = ms = j = fire = ads_btn = sp = 0
        if controlling:
            mf = (1 if key_down(app, "w", "arrow_up") else 0) - (1 if key_down(app, "s", "arrow_down") else 0)
            ms = (1 if key_down(app, "d", "arrow_right") else 0) - (1 if key_down(app, "a", "arrow_left") else 0)
            j = 1 if key_down(app, "space") else 0
            mw = app.mouseWatcherNode
            fire = 1 if mw.isButtonDown(MouseButton.one()) else 0
            ads_btn = 1 if mw.isButtonDown(MouseButton.three()) else 0
            if fire and not self.mouse_was_down:
                self.clicks += 1
            self.mouse_was_down = bool(fire)
            f = key_down(app, "f") or mw.isButtonDown(MouseButton.two())
            if f and not self.f_was_down:
                self.melees += 1
            self.f_was_down = f
            # sprint: hold Shift while running forward. Not while shooting or aiming, and only with stamina left.
            if key_down(app, "shift") and mf > 0 and not fire and not ads_btn and not frozen and self.me_state.get("st", 100) > 4:
                sp = 1
        self.ads += ((1 if ads_btn else 0) - self.ads) * min(1, dt * 12)
        self.sprint += (sp - self.sprint) * min(1, dt * 8)
        if alive and (mf or ms) and self.me_state.get("gr", 1) and controlling:
            self.step_t -= dt * (1.45 if sp else 1.0)
            if self.step_t <= 0:
                self.step_t = 0.4
                app.sounds.play("step", 0.22 if not sp else 0.3, random.uniform(0.85, 1.15))

        self.send_acc = min(0.2, self.send_acc + dt)
        while self.send_acc >= SEND_DT:
            self.send_acc -= SEND_DT
            msg = {"t": "in", "h": round(self.h % 360, 2), "pi": round(self.p, 2), "f": fire, "c": self.clicks, "m": self.melees,
                   "ads": ads_btn, "r": 1 if (controlling and key_down(app, "r")) else 0}
            if alive and self.pred:
                self.seq += 1
                msg.update(seq=self.seq, mf=mf, ms=ms, j=j, sp=sp)
                fm, fs, fj = (0, 0, 0) if frozen else (mf, ms, j)
                self.pending.append((self.seq, fm, fs, fj, self.h % 360, sp))
                self.pending = self.pending[-90:]
                move_player(self.pred, fm, fs, fj, self.h % 360, self.me_state.get("spd", 7) * (SPRINT_MUL if sp else 1.0),
                            SEND_DT, self.boxes, self.size)
            m.conn.send(msg)

        if self.pred:
            target = Vec3(self.pred["x"], self.pred["y"], self.pred["z"])
            if self.render_pos is None or (target - self.render_pos).length() > 3:
                self.render_pos = target
            else:
                self.render_pos += (target - self.render_pos) * min(1, dt * 22)

        pos = self.interp_rows("p")
        for pid in list(self.chars):
            if pid not in pos:
                self.chars.pop(pid).remove()
        alive_ids = []
        for pid, r in pos.items():
            if r[7]:
                alive_ids.append(pid)
            if pid == m.me and alive:
                continue
            info = m.infos.get(pid)
            if not info:
                continue
            c = self.chars.get(pid)
            if not c:
                c = make_player(self.root, info)
                tag = text(c.root, info["name"], 0.22, hexc(PLAYER_COLORS[info["color"] % 8]), font=self.font)
                tag.setZ(2.2)
                tag.setBillboardPointEye()
                self.chars[pid] = c
            c.set_gun(info["held"], m.parts)
            if r[7]:
                self.dead_at.pop(pid, None)
                c.root.show()
                c.root.setPos(r[1], r[2], r[3])
                c.root.setH(r[4])
                if hasattr(c, "revive"):
                    c.revive()
                else:
                    c.root.setR(0)
                c.animate(dt, r[8] if len(r) > 8 else 0, r[5])
            else:
                t0 = self.dead_at.setdefault(pid, now)
                if hasattr(c, "die"):
                    c.die()
                else:
                    c.root.setR(85 * min(1, (now - t0) * 3))
                if now - t0 > 4:
                    c.root.hide()
        m.alive_count = len(alive_ids)
        self.update_env()
        self.torch.setPos(app.camera.getPos(app.render))
        self.torch.setHpr(app.camera.getHpr(app.render))
        self.update_world(dt, now)
        self.update_prompt()

        cam = app.camera
        zoom = st["zoom"] if st else 1.3
        fov = app.settings["fov"] / (1 + (zoom - 1) * self.ads) + 7 * self.sprint * (1 - self.ads)
        app.camLens.setFov(fov)
        self.vm_lens.setAspectRatio(app.getAspectRatio())
        if alive and self.render_pos is not None:
            cam.setPos(self.render_pos.x, self.render_pos.y, self.render_pos.z + EYE_H)
            cam.setHpr(self.h, self.p, 0)
            self.dr.setActive(m.panel is None)
            self.update_viewmodel(dt, st, mf or ms)
            gap = (st["spread"] if st else 3) * (1.5 if (mf or ms or not self.me_state.get("gr", 1)) else 1) * (0.55 if ads_btn else 1)
            m.hud.set_crosshair(math.tan(math.radians(gap / 2)) / math.tan(math.radians(fov / 2)) + 0.01 if m.panel is None else None)
            m.hud.spec.setText("")
        else:
            self.dr.setActive(False)
            m.hud.set_crosshair(None)
            self.spectate(dt, alive_ids, pos)
        if self.vm_flash and self.vm_flash_t > 0:
            self.vm_flash_t -= dt
            if self.vm_flash_t <= 0:
                self.vm_flash.hide()
        self.fx.update(dt)
        self.sky.update()
        self.update_markers()
        self.update_hud(st, alive)

    def update_world(self, dt, now):
        pass

    def spectate(self, dt, alive_ids, pos):
        W, D = self.size
        t = time.monotonic() * 0.1
        self.m.app.camera.setPos(W / 2 + math.cos(t) * W * 0.6, D / 2 + math.sin(t) * D * 0.6, 22)
        self.m.app.camera.lookAt(W / 2, D / 2, 0)
        resp = self.me_state.get("resp", 0)
        self.m.hud.spec.setText(f"YOU'RE DOWN  -  back in your shop in {resp:.0f}s" if resp > 0 else "")

    def update_viewmodel(self, dt, st, moving):
        m = self.m
        info = m.infos.get(m.me)
        if not info:
            return
        key = tuple(sorted(info["held"].items()))
        if key != self.vm_key:
            if self.vm_gun:
                self.vm_gun.removeNode()
            self.vm_gun, self.vm_muzzle = build_gun(self.vm_holder, info["held"], m.parts)
            a0, b0 = self.vm_gun.getTightBounds() or ((0, 0, 0), (0, 0.3, 0))
            glen = b0[1] - a0[1]
            self.vm_gun.setPos(0, -a0[1] - glen * 0.38, 0)
            self.vm_muzzle = (self.vm_muzzle[0], self.vm_muzzle[1] - a0[1] - glen * 0.38, self.vm_muzzle[2])
            self.vm_key = key
            self.vm_flash = sphere_geom().copyTo(self.vm_holder)
            self.vm_flash.setPos(*self.vm_muzzle)
            self.vm_flash.setScale(0.045)
            self.vm_flash.setColor(1, 0.85, 0.4, 1)
            self.vm_flash.setLightOff()
            self.vm_flash.hide()
        self.bob += dt * ((13 if self.sprint > 0.5 else 9) if moving else 0)
        self.kick = max(0, self.kick - dt * 6)
        self.stab = max(0, self.stab - dt * 3.5)
        rel = self.me_state.get("reload", 0)
        dip = min(1, rel * 3) if rel > 0 else 0
        ads = self.ads
        bx = math.sin(self.bob) * 0.008 * (1 - ads)
        bz = abs(math.cos(self.bob)) * 0.008 * (1 - ads)
        lunge = math.sin(min(1, self.stab) * math.pi) * 0.25
        run = self.sprint
        self.vm_holder.setPos(0.17 * (1 - ads) + bx - lunge * 0.3 - 0.03 * run, 0.42 - self.kick * 0.05 + lunge,
                              -0.19 + 0.11 * ads - dip * 0.12 + bz - 0.05 * run)
        self.vm_holder.setHpr(lunge * 40 + 28 * run, self.kick * 5 - dip * 25 - 12 * run, -dip * 20)

    def update_hud(self, st, alive):
        m = self.m
        hud = m.hud
        me = self.me_state
        hud.set_vitals(max(0, me.get("hp", 100)), me.get("ar", 0), me.get("hu", 100), me.get("en", 100), bool(me.get("sl")))
        hud.set_stamina(me.get("st", 100) if alive else 100)
        if st:
            rel = self.me_state.get("reload", 0)
            if rel > 0:
                hud.ammo.setText("RELOAD")
                hud.ammo.setFg(H.ACCENT)
                hud.reload_bar.show(True)
                hud.reload_bar.set(1 - rel / max(0.1, st["reloadTime"]))
            elif self.me_state.get("jam"):
                hud.ammo.setText("JAMMED")
                hud.ammo.setFg(H.BAD)
            else:
                ammo = self.me_state.get("ammo", 0)
                hud.ammo.setText(str(ammo))
                hud.ammo.setFg(H.BAD if ammo <= max(1, st["magSize"] // 5) else H.WHITE)
                hud.reload_bar.show(False)
            info = m.infos.get(m.me, {})
            hud.ammo_sub.setText(f"{info.get('heldName', '')} ({info.get('heldCond', 1) * 100:.0f}%)  /  {st['magSize']}  {'AUTO' if st['auto'] else 'SEMI'}")

    def destroy(self):
        self.fx.clear()
        self.sky.destroy()
        self.m.hud.set_markers([])
        self.m.hud.set_stamina(100)
        self.torch.removeNode()
        self.m.hud.prompt.setText("")
        self.m.hud.spec.setText("")
        self.m.app.win.removeDisplayRegion(self.dr)
        self.vm_root.removeNode()
        self.root.removeNode()
        self.m.app.render.clearFog()
        self.m.app.camLens.setFov(self.m.app.settings["fov"])


# ====================================================================== TOWN (day)
CIVILIAN = ["#b55d3c", "#4f7a9a", "#7a6a4f", "#5f8a5a", "#8a4f6a", "#a08a3c", "#4f5a8a", "#8a8a8a"]


class TownView(FPSView):
    def __init__(self, m, world):
        t = world["town"]
        super().__init__(m, world["boxes"], world["size"], t.get("lightColor", "#fff2dc"), t.get("ambient", "#8a90a0"),
                         t.get("skyColor", "#a9c3d9"), t.get("fogColor", "#b9c9d6"), t.get("fogDensity", 0.006),
                         t.get("groundColor", "#7b6d58"), props=world.get("props", []), ground_mat=t.get("groundMat", "paving"))
        self.world = world
        for b in t.get("roads", []):
            box_min(self.static, b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"], hexc(b.get("color", "#666666")))
        self.static.flattenStrong()
        self.interior = PointLight("interior")
        self.interior.setColor((0.9, 0.82, 0.7, 1))
        self.interior.setAttenuation((1, 0.02, 0.012))
        self.interior_np = self.root.attachNewNode(self.interior)
        self.root.setLight(self.interior_np)
        self.targets = []
        for tg in world["targets"]:
            n = self.root.attachNewNode("target")
            n.setPos(tg["pos"][0], tg["pos"][1], 0)
            box(n, (0, 0, 0.6), (0.08, 0.08, 1.2), hexc("#333333"))
            board = box(n, (0, 0, 1.45), (0.9, 0.06, 0.9), hexc("#e8e2d0"))
            for r, col in ((0.32, "#c83c3c"), (0.18, "#e8e2d0"), (0.08, "#c83c3c")):
                box(n, (0, -0.035 - r * 0.01, 1.45), (r * 2, 0.02, r * 2), hexc(col))
            plot = world["plots"][tg["plot"]]
            n.setH(plot["rot"])
            self.targets.append({"np": n, "board": board, "flash": 0.0, "plot": tg["plot"], "idx": tg["idx"]})
        self.shelf_nodes = {}
        self.decor_nodes = {}
        self.sign_nodes = {}
        self.customers = {}
        self.cust_info = {}
        self.cust_snaps = []
        self.objects = world["objects"]
        self.set_palettes({k: t[k] for k in ("skyColor", "fogColor", "ambient", "lightColor", "fogDensity") if k in t},
                          t.get("night", {"skyColor": "#0c1120", "fogColor": "#131a29", "ambient": "#3c4560", "lightColor": "#8fa4e0", "fogDensity": 0.016}))
        self.build_stalls(world.get("vendors", []), t)
        for pl in world["plots"]:
            if pl.get("service_sign"):
                sg = text(self.root, "GUN CLEANING", 0.2, hexc("#ffd28a"), font=self.font)
                sg.setPos(*pl["service_sign"])
                sg.setH(pl["sign_rot"])
        m.hud.show_combat(True)
        m.hud.hint.setText("E use  -  Shift sprint  -  I inventory  -  H heal  -  G eat  -  1-6 pick gun  -  F1 help")

    def marker_list(self):
        m = self.m
        out = []
        g = m.guide.target() if getattr(m, "guide", None) else None
        if g:
            out.append((g[0], g[1], H.GOLD))
        pl = self.world["plots"][m.infos.get(m.me, {}).get("plot", 0)]
        if self.render_pos is not None:
            d = math.hypot(self.render_pos.x - pl["door"][0], self.render_pos.y - pl["door"][1])
            if d > 28 and not g:
                out.append(((pl["door"][0], pl["door"][1], 2.0), "YOUR SHOP", H.MUTED))
        return out

    def build_stalls(self, vendors, town):
        tv = {v["id"]: v for v in town.get("vendors", [])}
        for v in vendors:
            x, y = v["pos"][0], v["pos"][1]
            col = hexc(tv.get(v["id"], {}).get("color", "#c0392b"))
            n = self.root.attachNewNode("stall")
            for i in range(6):   # striped awning
                c = col if i % 2 == 0 else hexc("#f0ece0")
                box(n, (x - 1.75 + (i + 0.5) * 3.5 / 6, y + 1.6, 2.95), (3.5 / 6, 3.2, 0.12), c)
            sign = text(n, v["name"].upper(), 0.42, hexc("#ffe2a0"), font=self.font)
            sign.setPos(x, y + 0.45, 3.35)
            sign.setH(180 + v.get("h", 180) - 180)
            sign.setH(0 if v.get("h", 180) == 180 else 180)
            for pr in ({"mesh": "furniture/bookcaseOpen", "x": x - 1.6, "y": y + 2.7, "h": 180},
                       {"mesh": "furniture/cardboardBoxClosed", "x": x + 0.9, "y": y + 2.6, "h": 0},
                       {"mesh": {"food": "furniture/kitchenStove", "clinic": "furniture/kitchenFridgeSmall"}.get(v["kind"], "furniture/bookcaseClosed"),
                        "x": x + 0.2, "y": y + 2.75, "h": 180}):
                place_prop(n, pr)
            vend = make_customer(n, 3 + len(v["id"]))
            vend.root.setPos(x, y + 1.6, 0)
            vend.root.setH(180)
            vend.animate(0.01, 0, armed=False)
            if isinstance(vend, A.HumanChar):
                vend._play("legs", "Idle_FoldArms_Loop")
                vend._play("upper", "Idle_FoldArms_Loop")
            self.vendors_chars = getattr(self, "vendors_chars", []) + [vend]

    def on_snapshot(self, msg):
        super().on_snapshot(msg)
        self.cust_snaps.append((time.monotonic(), {r[0]: r for r in msg.get("c", [])}))
        self.cust_snaps = self.cust_snaps[-20:]

    def on_customer(self, msg):
        self.cust_info[msg["id"]] = msg

    def on_cbubble(self, msg):
        c = self.customers.get(msg["id"])
        if c:
            c["bubble"].node().setText(msg["text"])
            c["bubble"].node().setTextColor(*(H.GOOD if msg.get("happy") else H.BAD))
            if hasattr(c["char"], "gesture"):
                c["char"].gesture("Yes" if msg.get("happy") else ("Idle_No_Loop" if isinstance(c["char"], A.HumanChar) else "No"))

    def on_target_hit(self, msg):
        for t in self.targets:
            if t["plot"] == msg["plot"] and t["idx"] == msg["i"]:
                t["flash"] = 0.15
                self.fx.float_text(t["np"], str(msg["n"]), H.GOLD, z=2.2, font=self.font)

    def interp_customers(self):
        now = time.monotonic() - INTERP
        s = self.cust_snaps
        if not s:
            return {}
        for i in range(len(s) - 1, 0, -1):
            t0, f0 = s[i - 1]
            t1, f1 = s[i]
            if t0 <= now:
                k = 1.0 if t1 == t0 else min(1.0, (now - t0) / (t1 - t0))
                out = {}
                for cid, r1 in f1.items():
                    r0 = f0.get(cid, r1)
                    dh = (r1[3] - r0[3] + 180) % 360 - 180
                    out[cid] = (r0[1] + (r1[1] - r0[1]) * k, r0[2] + (r1[2] - r0[2]) * k, r0[3] + dh * k, r1[4])
                return out
        return {cid: (r[1], r[2], r[3], r[4]) for cid, r in s[-1][1].items()}

    def sync_shops(self):
        """Guns on shelves, decor and signs follow the players list."""
        m = self.m
        plots = self.world["plots"]
        seen = set()
        for info in m.infos.values():
            pl = plots[info["plot"]] if info["plot"] < len(plots) else None
            if not pl:
                continue
            for slot, item in enumerate(info.get("shelf", [])):
                key = (info["plot"], slot)
                seen.add(key)
                gid = item["gun"]["id"] if item else None
                cur = self.shelf_nodes.get(key)
                if cur and cur["gid"] == gid and cur.get("price") == (item or {}).get("price"):
                    continue
                if cur:
                    cur["np"].removeNode()
                    del self.shelf_nodes[key]
                if not item:
                    continue
                x, y, z, hd = pl["shelves"][slot]
                n = self.root.attachNewNode("shelfgun")
                n.setPos(x, y, z)
                n.setH(hd)
                g, _ = build_gun(n, item["gun"]["parts"], m.parts)
                c, size = bounds_center(g)
                g.setPos(-c[0], -c[1], -c[2] + 0.12)
                n.setScale(min(2.4, 1.3 / size))
                tag = text(self.root, f"${item['price']}", 0.2, H.GOLD, font=self.font)
                tag.setPos(x, y, z + 0.55)
                tag.setBillboardPointEye()
                tag.reparentTo(n)
                tag.setScale(0.2 / n.getScale().x)
                tag.setPos(0, 0, 0.72 / n.getScale().x)
                self.shelf_nodes[key] = {"np": n, "gid": gid, "price": item["price"]}
            for kind, store, src in (("decor", self.decor_nodes, "decor"), ("sign", self.sign_nodes, "sign")):
                uid = {"decor": "decor", "sign": "sign"}[kind]
                lvl = info.get("upgrades", {}).get(uid, 0)
                key = info["plot"]
                cur = store.get(key)
                want = (lvl, info["name"])
                if cur and cur["want"] == want:
                    continue
                if cur:
                    cur["np"].removeNode()
                n = self.root.attachNewNode(kind)
                for L in pl[src][:lvl]:
                    for b in L:
                        if "mesh" in b:
                            place_prop(n, b)
                            continue
                        bx = box_min(n, b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"], hexc(b.get("color", "#888888")))
                        if b.get("color", "").lower() in ("#ff9d3b",):
                            bx.setLightOff()
                if kind == "sign":
                    for b in pl.get("awning", []):
                        box_min(n, b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"], hexc(PLAYER_COLORS[info["color"] % 8]))
                    label = text(n, f"{info['name'].replace('[BOT] ', '').upper()}'S GUNS", 0.42,
                                 hexc("#ffd28a") if lvl else hexc("#d8d0c0"), font=self.font)
                    sx, sy, sz = pl["sign_text"]
                    label.setPos(sx, sy, sz)
                    label.setH(pl["sign_rot"])
                store[key] = {"np": n, "want": want}
        for key in list(self.shelf_nodes):
            if key not in seen:
                self.shelf_nodes.pop(key)["np"].removeNode()

    def describe(self, o):
        m = self.m
        if o["kind"] == "gate":
            return "[E] Go outside  (zombies - PvP when 2+ players are out)", True
        if o["kind"] == "vendor":
            v = next((v for v in self.world["vendors"] if v["id"] == o["vendor"]), None)
            if v and v.get("kind") == "collector":
                open_n = sum(1 for c in m.contracts if not c.get("done"))
                return f"[E] The Collector - {open_n} special order{'s' if open_n != 1 else ''}", True
            return (f"[E] {v['name']}" if v else None), bool(v)
        mine = m.infos.get(m.me, {}).get("plot") == o["plot"]
        owner = next((i for i in m.infos.values() if i["plot"] == o["plot"]), None)
        if o["kind"] == "shelf":
            shelf = owner.get("shelf", []) if owner else []
            item = shelf[o["slot"]] if o["slot"] < len(shelf) else None
            if mine:
                if o["slot"] >= (owner or {}).get("slots", 3):
                    return "Locked shelf (buy Display Racks)", True
                return (f"[E] Shelf {o['slot'] + 1}:  {item['gun']['name']}  ${item['price']}" if item else f"[E] Shelf {o['slot'] + 1}:  empty - display a gun"), True
            if item and owner:
                return f"[E] Buy {item['gun']['name']}  -  ${item['price']}  ({owner['name']})", True
            return None, False
        if not mine:
            return None, False
        if o["kind"] == "bed":
            return ("[E] Wake up" if self.me_state.get("sl") else f"[E] Sleep  (energy {self.me_state.get('en', 100):.0f}%)"), True
        if o["kind"] == "service":
            n = len(m.jobs)
            return f"[E] Service window - {n} client{'s' if n != 1 else ''} waiting" if n else "[E] Service window - nobody waiting", True
        return {"workbench": "[E] Workbench - assemble guns", "terminal": "[E] Supplier terminal - buy parts",
                "board": "[E] Upgrade board", "clean": "[E] Cleaning bench"}.get(o["kind"], ""), True

    def interact(self):
        o = self.prompt_obj
        if not o:
            return
        m = self.m
        mine = m.infos.get(m.me, {}).get("plot") == o["plot"]
        if o["kind"] == "gate":
            m.act({"a": "go_out"})
            return
        if o["kind"] == "vendor":
            v = next((v for v in self.world["vendors"] if v["id"] == o["vendor"]), None)
            if v and v.get("kind") == "collector":
                m.open_panel(P.ContractPanel(m))
            elif v:
                m.open_panel(P.VendorPanel(m, v))
            return
        if o["kind"] == "bed" and mine:
            m.act({"a": "wake" if self.me_state.get("sl") else "sleep"})
            return
        if o["kind"] == "clean" and mine:
            m.open_panel(P.CleaningPanel(m))
            return
        if o["kind"] == "service" and mine:
            m.open_panel(P.ServicePanel(m))
            return
        if o["kind"] == "shelf":
            if mine:
                m.open_panel(P.ShelfPanel(m, o["slot"]))
            else:
                owner = next((i for i in m.infos.values() if i["plot"] == o["plot"]), None)
                if owner:
                    m.open_panel(P.RivalShelfPanel(m, owner["id"], o["slot"]))
        elif mine and o["kind"] in ("workbench", "terminal", "board"):
            m.open_panel({"workbench": P.WorkbenchPanel, "terminal": P.SupplierPanel, "board": P.UpgradePanel}[o["kind"]](m))

    def update_world(self, dt, now):
        m = self.m
        self.sync_shops()
        cpos = self.interp_customers()
        for cid in list(self.customers):
            if cid not in cpos:
                self.customers.pop(cid)["char"].remove()
        for cid, (x, y, h, moving) in cpos.items():
            c = self.customers.get(cid)
            if not c:
                info = self.cust_info.get(cid, {})
                look = info.get("look", cid)
                ch = make_customer(self.root, look)
                pref = m.content.get("customers", {}).get(info.get("pref"), {})
                if info.get("svc"):
                    label = f"{info.get('name', '?')}:  needs a gun cleaned  (${info.get('budget', '?')})"
                else:
                    label = f"{info.get('name', '?')}:  wants {pref.get('label', 'A GUN')}  (${info.get('budget', '?')})"
                bub = text(ch.root, label, 0.13, H.WHITE, font=self.font)
                bub.setZ(2.15)
                bub.setBillboardPointEye()
                c = {"char": ch, "bubble": bub}
                self.customers[cid] = c
            c["char"].root.setPos(x, y, 0)
            c["char"].root.setH(h)
            c["char"].animate(dt, 3.2 if moving else 0, armed=False)
        for t in self.targets:
            if t["flash"] > 0:
                t["flash"] -= dt
                t["board"].setColor(*(hexc("#ffd75e") if t["flash"] > 0 else hexc("#e8e2d0")))
        if self.render_pos is not None:
            plots = self.world["plots"]
            near = min(plots, key=lambda p: (p["center"][0] - self.render_pos.x) ** 2 + (p["center"][1] - self.render_pos.y) ** 2)
            self.interior_np.setPos(near["center"][0], near["center"][1], 3.0)
            # move the shadow area in 6 m steps (no shimmering while walking)
            self.sun.setPos(round(self.render_pos.x / 6) * 6, round(self.render_pos.y / 6) * 6, 0)

    def destroy(self):
        for c in self.customers.values():
            c["char"].remove()
        for v in getattr(self, "vendors_chars", []):
            v.remove()
        super().destroy()


# ====================================================================== NIGHT
class OutsideView(FPSView):
    night = True

    def __init__(self, m, a):
        super().__init__(m, arena_boxes(a), a["size"], a.get("lightColor", "#9ab0ff"), a.get("ambient", "#3a4258"),
                         a.get("skyColor", "#0b0f1a"), a.get("fogColor", "#141a28"), a.get("fogDensity", 0.03),
                         a.get("groundColor", "#3a3d42"), props=a.get("props", []), ground_mat=a.get("groundMat", "asphalt"))
        self.static.flattenStrong()
        self.arena = a
        self.count_shown = 0
        self.zombies = {}
        self.crates = {}
        self.set_palettes(a.get("day", {}), a.get("night", {k: a[k] for k in ("skyColor", "fogColor", "ambient", "lightColor", "fogDensity") if k in a}))
        for ex in a.get("exits", []):
            n = self.root.attachNewNode("exit")
            n.setPos(ex[0], ex[1], 0)
            box(n, (0, 0, 1.4), (0.12, 0.12, 2.8), hexc("#333333"))
            board = box(n, (0, 0, 2.6), (2.0, 0.08, 0.6), hexc("#2e7d32"))
            board.setLightOff()
            t = text(n, "TOWN  ->", 0.32, (1, 1, 1, 1), font=self.font)
            t.setPos(0, -0.06, 2.5)
            beam = box(n, (0, 0, 6), (0.25, 0.25, 12), hexc("#7CFC9A"))
            beam.setLightOff()
            set_alpha(beam, 0.25)
            self.objects.append({"kind": "exit", "pos": [ex[0], ex[1], 1.2], "range": 4.0})
        self.dying = []
        self.zsnaps = []
        self.spec_idx = 0
        m.hud.show_combat(True)
        m.hud.hint.setText("Shift sprint  -  F bayonet  -  R reload  -  H heal  -  PvP is on while 2+ players are outside  -  F1 help")

    def marker_list(self):
        out = []
        for r in (self.last_loot or []):
            if len(r) > 4 and r[4]:
                out.append(((r[1], r[2], 1.5), "SUPPLY DROP" if r[5] <= 0 else f"DROP LANDING {r[5]:.0f}s", (1.0, 0.6, 0.25, 1)))
        for zz in self.zombies.values():
            if zz.get("boss"):
                p = zz["char"].root.getPos()
                if self.render_pos is not None and math.hypot(p.x - self.render_pos.x, p.y - self.render_pos.y) > 14:
                    out.append(((p.x, p.y, 3.2), "THE BUTCHER", H.BAD))
        for ex in self.arena.get("exits", []):
            out.append(((ex[0], ex[1], 2.6), "TOWN", H.GOOD))
        return out

    def on_damage(self, msg):
        super().on_damage(msg)
        if msg["v"] < 0 and msg.get("a") == self.m.me:
            zz = self.zombies.get(-msg["v"])
            if zz:
                root = zz["char"].root
                self.fx.float_text(root, str(msg["n"]), H.BAD if msg.get("hd") else H.GOLD, z=zz.get("top", 2.25),
                                   font=self.font, scale=0.3)

    def on_zhit(self, msg):
        zz = self.zombies.get(msg["id"])
        if zz:
            ch = zz["char"]
            if hasattr(ch, "gesture"):
                ch.gesture("Zombie_Scratch", 0.55)
            self.m.app.sounds.play("growl", self.dist_vol(ch.root.getPos()) * 0.7, random.uniform(0.85, 1.2))

    def on_loot_gone(self, msg):
        c = self.crates.pop(msg["id"], None)
        if c:
            c.removeNode()
        self.objects = [o for o in self.objects if o.get("loot") != msg["id"]]

    def describe(self, o):
        if o["kind"] == "exit":
            return "[E] Return to town", True
        if o["kind"] == "loot":
            return "[E] Search the supply crate", True
        if o["kind"] == "drop":
            row = next((r for r in (self.last_loot or []) if r[0] == o["loot"]), None)
            if row and row[5] > 0:
                return f"Supply drop landing in {row[5]:.0f}s...", False
            return "[E] Open the SUPPLY DROP", True
        return None, False

    def interact(self):
        o = self.prompt_obj
        if not o:
            return
        if o["kind"] == "exit":
            self.m.act({"a": "go_town"})
        elif o["kind"] in ("loot", "drop"):
            self.m.act({"a": "loot", "id": o["loot"]})

    last_loot = None

    def on_snapshot(self, msg):
        super().on_snapshot(msg)
        self.last_loot = msg.get("l", [])
        self.zsnaps.append((time.monotonic(), {r[0]: r for r in msg.get("z", [])}))
        self.zsnaps = self.zsnaps[-20:]

    def on_damage(self, msg):
        if msg["v"] < 0:
            z = self.zombies.get(-msg["v"])
            if z:
                z["char"].flinch = 0.5
        else:
            super().on_damage(msg)

    def on_zdead(self, msg):
        z = self.zombies.pop(msg["id"], None)
        if z:
            p = z["char"].root.getPos()
            self.fx.sparks(p + Vec3(0, 0, 1), (0.6, 0.1, 0.1, 1), 10, 4)
            if hasattr(z["char"], "die"):
                z["char"].die()
                self.dying.append((time.monotonic() + 2.5, z["char"]))
            else:
                z["char"].remove()

    def interp_zombies(self):
        now = time.monotonic() - INTERP
        s = self.zsnaps
        if not s:
            return {}
        for i in range(len(s) - 1, 0, -1):
            t0, f0 = s[i - 1]
            t1, f1 = s[i]
            if t0 <= now:
                k = 1.0 if t1 == t0 else min(1.0, (now - t0) / (t1 - t0))
                out = {}
                for zid, r1 in f1.items():
                    r0 = f0.get(zid, r1)
                    dh = (r1[4] - r0[4] + 180) % 360 - 180
                    out[zid] = (r0[1] + (r1[1] - r0[1]) * k, r0[2] + (r1[2] - r0[2]) * k, r0[3] + (r1[3] - r0[3]) * k,
                                r0[4] + dh * k, r1[5], r1[6], r1[7], math.hypot(r1[1] - r0[1], r1[2] - r0[2]) / max(1e-3, t1 - t0))
                return out
        return {zid: (r[1], r[2], r[3], r[4], r[5], r[6], r[7], 0) for zid, r in s[-1][1].items()}

    def update_world(self, dt, now):
        m = self.m
        app = m.app
        loot = {r[0]: r for r in (self.last_loot or [])}
        for lid in list(self.crates):
            if lid not in loot:
                self.on_loot_gone({"id": lid})
        for lid, r in loot.items():
            drop = len(r) > 4 and r[4]
            if lid not in self.crates:
                n = self.root.attachNewNode("crate")
                n.setPos(r[1], r[2], r[3])
                body = n.attachNewNode("body")
                if not place_prop(body, {"mesh": "props/Chest", "x": 0, "y": 0, "s": 1.6 if drop else 0.9}):
                    box(body, (0, 0, 0.4), (0.9, 0.6, 0.8), hexc("#8a6a3d"))
                if drop:   # supply drop: smoke beam you can see from anywhere, parachute while it falls
                    body.setColorScale(1.7, 1.15, 0.55, 1)
                    beam = box(n, (0, 0, 30), (0.5, 0.5, 60), hexc("#ff7a2a"))
                    beam.setLightOff()
                    beam.setFogOff()
                    set_alpha(beam, 0.35)
                    chute = n.attachNewNode("chute")
                    canopy = sphere_geom().copyTo(chute)
                    canopy.setColor(hexc("#e8e2d0"))
                    canopy.setScale(2.4, 2.4, 1.0)
                    canopy.setZ(5.0)
                    for sx in (-1, 1):
                        for sy in (-1, 1):
                            cord = box(chute, (sx * 1.0, sy * 1.0, 3.2), (0.03, 0.03, 3.6), hexc("#333333"))
                            cord.lookAt(chute, 0, 0, 1.4)
                    n.setPythonTag("chute", chute)
                    n.setPythonTag("body", body)
                else:
                    glow = box(n, (0, 0, 3), (0.12, 0.12, 6), hexc("#ffd75e"))
                    glow.setLightOff()
                    set_alpha(glow, 0.3)
                self.crates[lid] = n
                self.objects.append({"kind": "drop" if drop else "loot", "loot": lid, "pos": [r[1], r[2], 0.8],
                                     "range": 3.0 if drop else 2.6})
            if drop:
                n = self.crates[lid]
                fall = max(0.0, r[5]) * 5.0
                body, chute = n.getPythonTag("body"), n.getPythonTag("chute")
                body.setZ(fall)
                chute.setZ(fall)
                if fall <= 0 and not chute.isHidden():
                    chute.hide()
        types = list(m.content.get("zombies", {}).values())
        for item in [d for d in self.dying if d[0] < now]:
            self.dying.remove(item)
            item[1].remove()
        zpos = self.interp_zombies()
        for zid in list(self.zombies):
            if zid not in zpos:
                self.zombies.pop(zid)["char"].remove()
        for zid, (x, y, z, h, ti, hp, mhp, spd) in zpos.items():
            zz = self.zombies.get(zid)
            if not zz:
                zt = types[ti] if ti < len(types) else {}
                ch = make_zombie(self.root, zt, look=zid if isinstance(zid, int) else sum(map(ord, str(zid))))
                zz = {"char": ch, "groan": now + random.uniform(1, 6), "boss": bool(zt.get("boss")), "hp": None}
                # health bar (shown once hurt; always for the boss)
                top = 1.5 * zt.get("scale", 1.0)
                zz["top"] = top + 0.3
                bar = ch.root.attachNewNode("hpbar")
                bar.setZ(top + 0.17)
                bar.setBillboardPointEye()
                bar.setLightOff()
                box(bar, (0, 0.01, 0), (0.72, 0.01, 0.075), (0.05, 0.05, 0.05, 1))
                zz["fill"] = box(bar, (0, 0, 0), (0.68, 0.01, 0.05), (0.85, 0.15, 0.12, 1))
                bar.hide()
                zz["bar"] = bar
                if zz["boss"]:
                    ch.root.setColorScale(1.25, 0.7, 0.7, 1)
                    tag = text(ch.root, zt.get("name", "THE BUTCHER").upper(), 0.2, H.BAD, font=self.font)
                    tag.setZ(top + 0.37)
                    tag.setBillboardPointEye()
                self.zombies[zid] = zz
            ch = zz["char"]
            ch.root.setPos(x, y, z)
            ch.root.setH(h)
            ch.animate(dt, spd)
            if hp != zz["hp"]:
                zz["hp"] = hp
                frac = max(0.0, min(1.0, hp / max(1.0, mhp)))
                zz["fill"].setSx(max(0.001, 0.68 * frac))
                zz["fill"].setX(-0.34 * (1 - frac))
                if frac < 0.999 or zz["boss"]:
                    zz["bar"].show()
            if now > zz["groan"]:
                zz["groan"] = now + random.uniform(4, 10)
                app.sounds.play("groan", self.dist_vol(ch.root.getPos()) * 0.6, random.uniform(0.8, 1.2))

    def spectate(self, dt, alive_ids, pos):
        m = self.m
        app = m.app
        others = [pid for pid in alive_ids if pid != m.me]
        mw = app.mouseWatcherNode
        down = bool(mw and mw.hasMouse() and mw.isButtonDown(MouseButton.one()) and not m.menu_open)
        if down and not self.mouse_was_down and others:
            self.spec_idx += 1
        self.mouse_was_down = down
        if others:
            pid = others[self.spec_idx % len(others)]
            r = pos[pid]
            fx, fy, _ = aim_vec(r[4], 0)
            target = Point3(r[1], r[2], r[3] + 1.6)
            back = Vec3(-fx * 4.5, -fy * 4.5, 1.0)
            dist = back.length()
            back.normalize()
            t, hit = ray_world((target.x, target.y, target.z), (back.x, back.y, back.z), self.boxes, dist)
            want = target + back * max(0.5, (t - 0.35) if hit else dist)
            cur = app.camera.getPos()
            app.camera.setPos(want if (want - cur).length() > 12 else cur + (want - cur) * min(1, dt * 8))
            app.camera.lookAt(target)
            resp = self.me_state.get("resp", 0)
            m.hud.spec.setText(f"YOU'RE DOWN  -  watching {m.infos.get(pid, {}).get('name', '?')}  -  back in town in {resp:.0f}s")
        else:
            super().spectate(dt, alive_ids, pos)

    def update_hud(self, st, alive):
        super().update_hud(st, alive)
        self.m.hud.alive.setText(f"{self.m.out_count} OUTSIDE   {len(self.zombies)} ZOMBIES")

    def destroy(self):
        for z in self.zombies.values():
            z["char"].remove()
        for _, ch in self.dying:
            ch.remove()
        self.m.hud.alive.setText("")
        super().destroy()
