"""Building materials: photo textures (ambientCG, CC0) on boxes with world-space UVs and normal maps.

A box picks its material with "mat" (brick, plaster, concrete, corrugated, metal, siding, planks, roof, asphalt,
paving - or any <name>_color.jpg a mod adds to models/materials/). Boxes without "mat" get one guessed from their
colour. Textures repeat every N metres instead of stretching, so a 100 m wall looks as good as a crate.
"""
import colorsys
import json
import os

from panda3d.core import (Filename, Geom, GeomNode, GeomTriangles, GeomVertexArrayFormat, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, InternalName, SamplerState, Texture, TextureStage)

from . import assets as A
from . import geom as G

_tex = {}
_tiles = {}
_fmt = None
NORMAL_STAGE = TextureStage("normal")
NORMAL_STAGE.setMode(TextureStage.MNormal)
NORMAL_STAGE.setSort(10)


def _format():
    global _fmt
    if _fmt is None:
        a = GeomVertexArrayFormat()
        a.addColumn(InternalName.getVertex(), 3, Geom.NT_float32, Geom.C_point)
        a.addColumn(InternalName.getNormal(), 3, Geom.NT_float32, Geom.C_normal)
        a.addColumn(InternalName.getColor(), 4, Geom.NT_uint8, Geom.C_color)
        a.addColumn(InternalName.getTexcoord(), 2, Geom.NT_float32, Geom.C_texcoord)
        a.addColumn(InternalName.getTangent(), 3, Geom.NT_float32, Geom.C_vector)
        a.addColumn(InternalName.getBinormal(), 3, Geom.NT_float32, Geom.C_vector)
        _fmt = GeomVertexFormat.registerFormat(GeomVertexFormat(a))
    return _fmt


def _find(name, kind):
    if A.ROOT is None:
        return None
    mods = os.path.join(A.ROOT, "mods")
    found = None
    for mod in sorted(os.listdir(mods), key=lambda m: (m != "core", m)):
        p = os.path.join(mods, mod, "models", "materials", f"{name}_{kind}.jpg")
        if os.path.isfile(p):
            found = p
        mj = os.path.join(mods, mod, "models", "materials", "materials.json")
        if kind == "color" and os.path.isfile(mj) and not _tiles.get("_read_" + mod):
            _tiles["_read_" + mod] = 1
            try:
                with open(mj, encoding="utf-8") as f:
                    for k, v in json.load(f).items():
                        _tiles[k] = float(v.get("tile", 2.5))
            except (OSError, ValueError):
                pass
    return found


def textures(name):
    """(color, normal) textures for a material, or (None, None) if it isn't installed."""
    if name not in _tex:
        out = []
        for kind in ("color", "normal"):
            p = _find(name, kind)
            t = A._loader.loadTexture(Filename.fromOsSpecific(p)) if p else None
            if t:
                t.setMinfilter(SamplerState.FT_linear_mipmap_linear)
                t.setMagfilter(SamplerState.FT_linear)
                t.setAnisotropicDegree(8)
                t.setWrapU(Texture.WM_repeat)
                t.setWrapV(Texture.WM_repeat)
            out.append(t)
        _tex[name] = tuple(out)
    return _tex[name]


def available(name):
    return textures(name)[0] is not None


def tile(name):
    textures(name)
    return _tiles.get(name, 2.5)


def guess(b):
    """Material for a box without "mat", from its colour and shape."""
    c = b.get("color", "#777777").lstrip("#")
    try:
        r, g, bl = (int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return "concrete"
    h, s, v = colorsys.rgb_to_hsv(r, g, bl)
    big = max(b.get("w", 1), b.get("d", 1)) > 4 and b.get("h", 1) > 2.4
    if s < 0.12:
        return "concrete" if v > 0.3 else "metal"
    if 0.03 < h < 0.13:          # browns / tans
        if big:
            return "brick" if s > 0.22 else "plaster"
        return "planks" if b.get("h", 1) < 2 else "siding"
    if 0.2 < h < 0.55:           # greens / teals: painted steel
        return "metal"
    if 0.55 <= h < 0.75:
        return "corrugated"
    return "plaster" if big else "siding"


def tint_for(b):
    if b.get("tint"):
        return G.hexc(b["tint"])
    if b.get("mat"):
        return (1, 1, 1, 1)
    r, g, bl, _ = G.hexc(b.get("color", "#888888"))
    m = max(1e-3, (r + g + bl) / 3)
    k = 0.3   # keep most of the photo's own colour, nudge it toward the box colour
    return tuple(min(1.25, (1 - k) + k * ch / m) for ch in (r, g, bl)) + (1,)


# (normal, tangent = +u direction, binormal = +v direction) for the 6 faces
_FACES = [
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
    ((0, 1, 0), (-1, 0, 0), (0, 0, 1)),
    ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ((0, 0, -1), (1, 0, 0), (0, -1, 0)),
]


def box_geom(x, y, z, w, d, h, tile_m, color=(1, 1, 1, 1), skip_bottom=True):
    """A box from (x, y, z) to (x+w, y+d, z+h) with UVs in world metres / tile_m."""
    vd = GeomVertexData("mbox", _format(), Geom.UH_static)
    vw, nw, cw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "normal"), GeomVertexWriter(vd, "color")
    tw, tg, bn = GeomVertexWriter(vd, "texcoord"), GeomVertexWriter(vd, "tangent"), GeomVertexWriter(vd, "binormal")
    tris = GeomTriangles(Geom.UH_static)
    c = (x + w / 2, y + d / 2, z + h / 2)
    half = (w / 2, d / 2, h / 2)
    i = 0
    for n, t, b in _FACES:
        if skip_bottom and n[2] < 0 and z <= 0.01:
            continue
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            p = [c[k] + n[k] * half[k] + t[k] * su * half[k] + b[k] * sv * half[k] for k in range(3)]
            vw.addData3(*p)
            nw.addData3(*n)
            cw.addData4(*color)
            u = sum(p[k] * t[k] for k in range(3)) / tile_m
            v = sum(p[k] * b[k] for k in range(3)) / tile_m
            tw.addData2(u, v)
            tg.addData3(*t)
            bn.addData3(*b)
        tris.addVertices(i, i + 1, i + 2)
        tris.addVertices(i, i + 2, i + 3)
        i += 4
    g = Geom(vd)
    g.addPrimitive(tris)
    return g


class Builder:
    """Collects boxes per material, then makes one merged, textured node per material."""

    def __init__(self, parent):
        self.parent = parent
        self.nodes = {}

    def add(self, x, y, z, w, d, h, mat, color=(1, 1, 1, 1)):
        if not available(mat):
            return False
        if mat not in self.nodes:
            np = self.parent.attachNewNode(GeomNode("mat_" + mat))
            col, nrm = textures(mat)
            np.setTexture(col)
            if nrm is not None and G.FANCY:
                np.setTexture(NORMAL_STAGE, nrm)
            self.nodes[mat] = np
        self.nodes[mat].node().addGeom(box_geom(x, y, z, max(w, 1e-3), max(d, 1e-3), max(h, 1e-3), tile(mat), color))
        return True

    def add_box(self, b):
        mat = b.get("mat") or guess(b)
        return self.add(b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"], mat, tint_for(b))

    def finish(self):
        for np in self.nodes.values():
            np.flattenStrong()
