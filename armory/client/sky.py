"""Sky: gradient dome, sun, moon and stars, drawn in their own display region behind the world.

Kept in a separate scene so it never ends up in shadow maps or fog. Sky.set() takes plain colours, so the
view can blend smoothly between day, dusk, night and a Blood Moon.
"""
import math
import random

from panda3d.core import (Camera, Geom, GeomNode, GeomPoints, GeomTriangles, GeomVertexData, GeomVertexFormat,
                          GeomVertexWriter, NodePath, PerspectiveLens, TransparencyAttrib, Vec3)


RINGS, SEGS = 14, 28
LOW = -12.0          # the dome dips a little below the horizon


class Sky:
    def __init__(self, app):
        self.app = app
        self.scene = NodePath("sky")
        self.scene.setLightOff()
        self.scene.setFogOff()
        self.scene.setShaderOff()
        self.scene.setDepthWrite(False)
        self.scene.setDepthTest(False)
        self.lens = PerspectiveLens()
        self.lens.setNearFar(1, 2000)
        self.cam = self.scene.attachNewNode(Camera("skycam", self.lens))
        self.dr = app.win.makeDisplayRegion()
        self.dr.setSort(-10)
        self.dr.setCamera(self.cam)
        self.dr.setClearColorActive(False)
        self.dr.setClearDepthActive(False)
        # the window clears first, then this region (sort -10), then the main view draws on top of it

        vd = GeomVertexData("dome", GeomVertexFormat.getV3c4(), Geom.UHDynamic)
        vw, cw = GeomVertexWriter(vd, "vertex"), GeomVertexWriter(vd, "color")
        self.tees = []
        for r in range(RINGS + 1):
            el = LOW + (90 - LOW) * r / RINGS
            t = max(0.0, min(1.0, el / 55.0)) ** 0.7
            for s in range(SEGS + 1):
                az = math.tau * s / SEGS
                e = math.radians(el)
                vw.addData3(math.cos(e) * math.cos(az) * 500, math.cos(e) * math.sin(az) * 500, math.sin(e) * 500)
                cw.addData4(1, 1, 1, 1)
                self.tees.append(t)
        tris = GeomTriangles(Geom.UHStatic)
        for r in range(RINGS):
            for s in range(SEGS):
                a = r * (SEGS + 1) + s
                b = a + SEGS + 1
                tris.addVertices(a, a + 1, b)
                tris.addVertices(a + 1, b + 1, b)
        g = Geom(vd)
        g.addPrimitive(tris)
        gn = GeomNode("dome")
        gn.addGeom(g)
        self.dome = self.scene.attachNewNode(gn)
        self.dome.setTwoSided(True)
        self.vd = vd

        rng = random.Random(7)
        sd = GeomVertexData("stars", GeomVertexFormat.getV3c4(), Geom.UHStatic)
        sw, sc = GeomVertexWriter(sd, "vertex"), GeomVertexWriter(sd, "color")
        pts = GeomPoints(Geom.UHStatic)
        for i in range(420):
            az, el = rng.uniform(0, math.tau), math.asin(rng.uniform(0.06, 1.0))
            sw.addData3(math.cos(el) * math.cos(az) * 480, math.cos(el) * math.sin(az) * 480, math.sin(el) * 480)
            b = rng.uniform(0.45, 1.0)
            sc.addData4(b, b, b * rng.uniform(0.9, 1.0), 1)
            pts.addVertex(i)
        sg = Geom(sd)
        sg.addPrimitive(pts)
        sn = GeomNode("stars")
        sn.addGeom(sg)
        self.stars = self.scene.attachNewNode(sn)
        self.stars.setRenderModeThickness(2)
        self.stars.setTransparency(TransparencyAttrib.MAlpha)

        def disc(radius, alpha_mid, alpha_rim, solid=0.0):
            # a round disc that faces the viewer; brightness falls off toward the rim (soft glow) or stays solid
            dd = GeomVertexData("disc", GeomVertexFormat.getV3c4(), Geom.UHStatic)
            dw, dc = GeomVertexWriter(dd, "vertex"), GeomVertexWriter(dd, "color")
            dw.addData3(0, 0, 0)
            dc.addData4(1, 1, 1, alpha_mid)
            n_seg = 48
            ring = [(solid, alpha_mid), (1.0, alpha_rim)] if solid else [(1.0, alpha_rim)]
            for frac, al in ring:
                for i in range(n_seg + 1):
                    a = math.tau * i / n_seg
                    dw.addData3(math.cos(a) * radius * frac, 0, math.sin(a) * radius * frac)
                    dc.addData4(1, 1, 1, al)
            tr = GeomTriangles(Geom.UHStatic)
            for i in range(n_seg):
                tr.addVertices(0, 1 + i, 2 + i)
            if solid:
                o = n_seg + 2
                for i in range(n_seg):
                    tr.addVertices(1 + i, o + i, o + i + 1)
                    tr.addVertices(1 + i, o + i + 1, 2 + i)
            dg = Geom(dd)
            dg.addPrimitive(tr)
            dn = GeomNode("disc")
            dn.addGeom(dg)
            n = self.scene.attachNewNode(dn)
            n.setTwoSided(True)
            n.setTransparency(TransparencyAttrib.MAlpha)
            return n
        self.sun_glow = disc(95, 0.5, 0.0)
        self.sun_glow.setColorScale(1, 0.86, 0.6, 1)
        self.sun = disc(19, 1.0, 0.0, solid=0.86)
        self.sun.setColorScale(1, 0.97, 0.86, 1)
        self.moon_glow = disc(60, 0.22, 0.0)
        self.moon = disc(13, 1.0, 0.0, solid=0.9)
        self.key = None

    def set(self, zenith, horizon, sun_dir, sun_alpha, moon_dir, moon_alpha, stars, moon_color=(0.9, 0.92, 1.0)):
        key = tuple(round(v, 3) for v in (*zenith[:3], *horizon[:3], *sun_dir, sun_alpha, moon_alpha, stars, *moon_color))
        if key == self.key:
            return
        self.key = key
        cw = GeomVertexWriter(self.vd, "color")
        zr, zg, zb = zenith[:3]
        hr, hg, hb = horizon[:3]
        for t in self.tees:
            cw.setData4(hr + (zr - hr) * t, hg + (zg - hg) * t, hb + (zb - hb) * t, 1)
        sd = Vec3(*sun_dir)
        for n, a in ((self.sun, sun_alpha), (self.sun_glow, sun_alpha)):
            n.setPos(sd * 450)
            n.lookAt(0, 0, 0)
            n.setAlphaScale(max(0.0, min(1.0, a)))
            n.show() if a > 0.01 else n.hide()
        md = Vec3(*moon_dir)
        for n, a in ((self.moon, moon_alpha), (self.moon_glow, moon_alpha)):
            n.setPos(md * 450)
            n.lookAt(0, 0, 0)
            n.setAlphaScale(max(0.0, min(1.0, a)))
            n.show() if a > 0.01 else n.hide()
        ma = max(0.0, min(1.0, moon_alpha))
        self.moon.setColorScale(moon_color[0], moon_color[1], moon_color[2], ma)
        self.moon_glow.setColorScale(moon_color[0], moon_color[1], moon_color[2], ma)
        self.stars.setAlphaScale(max(0.0, min(1.0, stars)))
        self.stars.show() if stars > 0.01 else self.stars.hide()

    def update(self):
        app = self.app
        self.cam.setHpr(app.camera.getHpr(app.render))
        fov = app.camLens.getFov()
        self.lens.setFov(fov[0], fov[1])

    def destroy(self):
        self.app.win.removeDisplayRegion(self.dr)
        self.scene.removeNode()
