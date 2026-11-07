"""Procedural geometry: everything in the game is built from boxes (easy to mod - no model files)."""
import math

from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData, GeomVertexFormat, GeomVertexWriter,
                          NodePath, PNMImage, Texture, TextNode, TransparencyAttrib, SamplerState)

FANCY = True  # per-pixel lighting + shadows; False = compatible mode for old GPUs / older Macs


def shader_auto(np):
    if FANCY:
        np.setShaderAuto()


PLAYER_COLORS = ["#e8892b", "#3fa7ff", "#5fd35f", "#e04848", "#b46cff", "#ffd23f", "#3fe0d0", "#ff6fb5"]


def hexc(s, a=1.0):
    try:
        s = s.lstrip("#")
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        return (int(s[0:2], 16) / 255, int(s[2:4], 16) / 255, int(s[4:6], 16) / 255, a)
    except Exception:
        return (0.5, 0.5, 0.5, a)


def mix(c, f):
    return (min(1, c[0] * f), min(1, c[1] * f), min(1, c[2] * f), c[3] if len(c) > 3 else 1)


_cube = None
_sphere = None


def cube_geom():
    """Unit cube centred at origin, with normals and UVs."""
    global _cube
    if _cube is not None:
        return _cube
    fmt = GeomVertexFormat.getV3n3t2()
    vd = GeomVertexData("cube", fmt, Geom.UHStatic)
    vw, nw, tw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "normal"), GeomVertexWriter(vd, "texcoord")
    tris = GeomTriangles(Geom.UHStatic)
    faces = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
             ((0, 1, 0), (-1, 0, 0), (0, 0, 1)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
             ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (1, 0, 0), (0, -1, 0))]
    i = 0
    for n, u, v in faces:
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vw.addData3(n[0] * .5 + u[0] * su * .5 + v[0] * sv * .5,
                        n[1] * .5 + u[1] * su * .5 + v[1] * sv * .5,
                        n[2] * .5 + u[2] * su * .5 + v[2] * sv * .5)
            nw.addData3(*n)
            tw.addData2((su + 1) / 2, (sv + 1) / 2)
        tris.addVertices(i, i + 1, i + 2)
        tris.addVertices(i, i + 2, i + 3)
        i += 4
    g = Geom(vd)
    g.addPrimitive(tris)
    node = GeomNode("cube")
    node.addGeom(g)
    _cube = NodePath(node)
    return _cube


def sphere_geom():
    global _sphere
    if _sphere is not None:
        return _sphere
    fmt = GeomVertexFormat.getV3n3()
    vd = GeomVertexData("sphere", fmt, Geom.UHStatic)
    vw, nw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "normal")
    rings, segs = 8, 14
    for r in range(rings + 1):
        th = math.pi * r / rings
        for s in range(segs + 1):
            ph = 2 * math.pi * s / segs
            x, y, z = math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)
            vw.addData3(x, y, z)
            nw.addData3(x, y, z)
    tris = GeomTriangles(Geom.UHStatic)
    for r in range(rings):
        for s in range(segs):
            a = r * (segs + 1) + s
            b = a + segs + 1
            tris.addVertices(a, b, a + 1)
            tris.addVertices(a + 1, b, b + 1)
    g = Geom(vd)
    g.addPrimitive(tris)
    node = GeomNode("sphere")
    node.addGeom(g)
    _sphere = NodePath(node)
    return _sphere


def box(parent, pos, size, color, name="box"):
    np = cube_geom().copyTo(parent)
    np.setName(name)
    np.setPos(*pos)
    np.setScale(max(1e-4, size[0]), max(1e-4, size[1]), max(1e-4, size[2]))
    np.setColor(*(color if isinstance(color, tuple) else hexc(color)))
    return np


def box_min(parent, x, y, z, w, d, h, color):
    return box(parent, (x + w / 2, y + d / 2, z + h / 2), (w, d, h), color)


def grid_texture(base=(0.5, 0.5, 0.5), line=0.82, size=128, cells=4):
    img = PNMImage(size, size)
    step = size // cells
    for x in range(size):
        for y in range(size):
            v = 1.0
            if x % step in (0, 1) or y % step in (0, 1):
                v = line
            n = ((x * 7919 + y * 104729) % 97) / 97.0
            v *= 0.94 + n * 0.06
            img.setXel(x, y, v, v, v)
    tex = Texture("grid")
    tex.load(img)
    tex.setMinfilter(SamplerState.FT_linear_mipmap_linear)
    tex.setMagfilter(SamplerState.FT_linear)
    tex.setAnisotropicDegree(8)
    return tex


def text(parent, s, scale=1.0, color=(1, 1, 1, 1), align="center", font=None, shadow=True, name="text"):
    tn = TextNode(name)
    tn.setText(s)
    tn.setAlign({"center": TextNode.ACenter, "left": TextNode.ALeft, "right": TextNode.ARight}[align])
    tn.setTextColor(*color)
    if font:
        tn.setFont(font)
    if shadow:
        tn.setShadow(0.06, 0.06)
        tn.setShadowColor(0, 0, 0, 0.8)
    np = parent.attachNewNode(tn)
    np.setScale(scale)
    np.setLightOff()
    return np


# ------------------------------------------------------------------ guns
ORDER = ["stock", "magazine", "grip", "barrel", "muzzle", "bayonet", "receiver", "sight"]


def gun_layout(loadout, parts):
    rcv = parts.get(loadout.get("receiver", ""))
    if not rcv:
        return []
    L = rcv.get("length", 0.25)
    m = {"barrel": [0, L, 0], "stock": [0, 0, 0], "magazine": [0, L * 0.6, -0.04], "sight": [0, L * 0.45, 0.04],
         "grip": [0, L * 0.9, -0.04]}
    m.update(rcv.get("mounts", {}))
    pos = {"receiver": (0, 0, 0)}
    for s in ("barrel", "stock", "magazine", "sight", "grip"):
        pos[s] = tuple(m[s])
    brl = parts.get(loadout.get("barrel", ""))
    bx, by, bz = pos["barrel"]
    if brl:
        mz = brl.get("mounts", {}).get("muzzle", [0, brl.get("length", 0.1), 0])
        pos["muzzle"] = (bx + mz[0], by + mz[1], bz + mz[2])
    else:
        pos["muzzle"] = (bx, by, bz)
    mx, my, mz = pos["muzzle"]
    pos["bayonet"] = (mx, my - 0.07, mz - 0.035)
    out = []
    for slot in ORDER:
        p = parts.get(loadout.get(slot, ""))
        if p and p["slot"] == slot:
            out.append((p, pos[slot]))
    return out, pos["muzzle"]


def build_gun(parent, loadout, parts, flatten=True):
    """Returns (NodePath, muzzle_pos). Gun points +Y, origin at back of receiver."""
    root = parent.attachNewNode("gun")
    res = gun_layout(loadout, parts)
    if not res:
        return root, (0, 0.3, 0)
    lay, muzzle = res
    for p, (ox, oy, oz) in lay:
        for b in p.get("model", []):
            px, py, pz = b.get("p", (0, 0, 0))
            box(root, (ox + px, oy + py, oz + pz), b.get("s", (0.05, 0.05, 0.05)), b.get("c", "#555555"))
    if flatten:
        root.flattenStrong()
    return root, muzzle


def build_part(parent, part):
    root = parent.attachNewNode("part")
    for b in part.get("model", []):
        box(root, b.get("p", (0, 0, 0)), b.get("s", (0.05, 0.05, 0.05)), b.get("c", "#555555"))
    root.flattenStrong()
    return root


def bounds_center(np):
    a, b = np.getTightBounds() or ((0, 0, 0), (0, 0, 0))
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2), max(b[0] - a[0], b[1] - a[1], b[2] - a[2], 1e-3)


# ------------------------------------------------------------------ characters
class Character:
    """Blocky person: legs/arms swing when walking. Holds a gun at chest height (or claws, for zombies)."""

    def __init__(self, parent, color_hex, gun_scale=1.6, skin_hex="#e0b48a", zombie=False, pants_hex="#2b2e33", hat=True):
        c = hexc(color_hex)
        dark = mix(c, 0.55)
        skin = hexc(skin_hex)
        self.zombie = zombie
        self.root = parent.attachNewNode("char")
        self.body = self.root.attachNewNode("body")
        self.hip_l = self.body.attachNewNode("hl")
        self.hip_l.setPos(-0.14, 0, 0.82)
        box(self.hip_l, (0, 0, -0.4), (0.17, 0.2, 0.8), hexc(pants_hex))
        self.hip_r = self.body.attachNewNode("hr")
        self.hip_r.setPos(0.14, 0, 0.82)
        box(self.hip_r, (0, 0, -0.4), (0.17, 0.2, 0.8), hexc(pants_hex))
        box(self.body, (0, 0, 1.12), (0.52, 0.3, 0.62), c)
        box(self.body, (0, 0.01, 1.2), (0.54, 0.32, 0.18), dark)
        self.head = self.body.attachNewNode("head")
        self.head.setPos(0, 0, 1.62)
        box(self.head, (0, 0, 0), (0.3, 0.3, 0.3), skin)
        if hat:
            box(self.head, (0, 0, 0.12), (0.34, 0.34, 0.12), dark)
        box(self.head, (0, 0.155, 0.02), (0.22, 0.02, 0.06), hexc("#ff3020") if zombie else hexc("#111111"))
        self.arm_l = self.body.attachNewNode("al")
        self.arm_l.setPos(-0.33, 0, 1.38)
        box(self.arm_l, (0, 0.18, -0.12), (0.13, 0.45, 0.13), c)
        self.arm_r = self.body.attachNewNode("ar")
        self.arm_r.setPos(0.33, 0, 1.38)
        box(self.arm_r, (0, 0.18, -0.12), (0.13, 0.45, 0.13), c)
        self.gun_mount = self.body.attachNewNode("gunmount")
        self.gun_mount.setPos(0.1, 0.42, 1.25)
        self.gun_mount.setScale(gun_scale)
        self.gun = None
        self.gun_key = None
        self.muzzle = (0, 0.3, 0)
        self.phase = 0.0
        self.flinch = 0.0

    def set_gun(self, loadout, parts):
        key = tuple(sorted(loadout.items()))
        if key == self.gun_key:
            return False
        if self.gun:
            self.gun.removeNode()
        self.gun, self.muzzle = build_gun(self.gun_mount, loadout, parts)
        self.gun_key = key
        return True

    def muzzle_world(self, render):
        return render.getRelativePoint(self.gun_mount, self.muzzle)

    def animate(self, dt, speed, aim_pitch=0.0, armed=True):
        self.phase += dt * speed * 1.7
        sw = math.sin(self.phase) * min(1.0, speed / 6) * 38
        self.hip_l.setP(sw)
        self.hip_r.setP(-sw)
        self.body.setZ(abs(math.sin(self.phase)) * 0.05 * min(1, speed / 6))
        if self.zombie:
            self.arm_l.setP(10 + math.sin(self.phase * 0.7) * 8)
            self.arm_r.setP(10 - math.sin(self.phase * 0.7) * 8)
        elif armed:
            self.arm_l.setP(aim_pitch + 4)
            self.arm_r.setP(aim_pitch + 4)
        else:
            self.arm_l.setP(-70 - sw * 0.6)
            self.arm_r.setP(-70 + sw * 0.6)
        self.gun_mount.setP(aim_pitch)
        self.flinch = max(0.0, self.flinch - dt * 4)
        self.body.setR(math.sin(self.flinch * 20) * self.flinch * 8)

    def remove(self):
        self.root.removeNode()


def set_alpha(np, a):
    np.setTransparency(TransparencyAttrib.MAlpha)
    np.setAlphaScale(a)
