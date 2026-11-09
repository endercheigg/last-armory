"""Shop UIs: supplier terminal, workbench (with live 3D preview), shelves, rival shelves, upgrade board."""
import math

from direct.gui.DirectGui import DGG, DirectButton, DirectEntry, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import Camera, NodePath, PerspectiveLens, TextNode, Vec3

from ..gun import RARITY, RARITY_COLORS, SLOTS, compute_stats, gun_value
from . import hud as H
from .geom import bounds_center, build_gun, hexc

PANEL_BG = (0.06, 0.07, 0.09, 0.95)
BTN = ((0.2, 0.22, 0.27, 1), (0.3, 0.33, 0.4, 1), (0.3, 0.33, 0.4, 1), (0.13, 0.13, 0.15, 1))
BTN_HOT = ((1.0, 0.55, 0.15, 1), (1.0, 0.68, 0.32, 1), (1.0, 0.68, 0.32, 1), (0.25, 0.2, 0.15, 1))

STAT_LABELS = {"damage": "damage", "fireRate": "fire rate", "spread": "spread", "recoil": "recoil", "range": "range",
               "magSize": "magazine", "reloadTime": "reload time", "moveSpeed": "move speed", "zoom": "zoom",
               "melee": "melee", "pellets": "bullets", "explosionRadius": "blast radius", "headshot": "headshot dmg"}


def part_summary(p):
    out = []
    if p["slot"] == "receiver":
        s = p["set"]
        out.append(f"DMG {s.get('damage', 12):.0f}" + (f"x{s['pellets']}" if s.get("pellets", 1) > 1 else ""))
        out.append(f"{s.get('fireRate', 4):.1f}/s")
        out.append("AUTO" if s.get("auto") else "SEMI")
        out.append(f"MAG {s.get('magSize', 10)}")
        if s.get("explosionRadius"):
            out.append("EXPLOSIVE")
    for k, v in p["add"].items():
        out.append(f"{'+' if v >= 0 else ''}{v:g} {STAT_LABELS.get(k, k)}")
    for k, v in p["mul"].items():
        pct = round((v - 1) * 100)
        if pct:
            out.append(f"{'+' if pct > 0 else ''}{pct}% {STAT_LABELS.get(k, k)}")
    return "   ".join(out[:4])


def gun_summary(st):
    return (f"DMG {st['damage']:.0f}{'x' + str(st['pellets']) if st['pellets'] > 1 else ''}   {st['fireRate']:.1f}/s   "
            f"RANGE {st['range']:.0f}m   MAG {st['magSize']}   SPREAD {st['spread']:.1f}   {'AUTO' if st['auto'] else 'SEMI'}")


class Panel:
    title = ""
    refresh_on_players = True

    @property
    def typing(self):
        e = getattr(self, "entry", None)
        try:
            return bool(e is not None and e["focus"])
        except Exception:
            return False

    def __init__(self, m, w=1.25, h=0.85):
        self.m = m
        self.app = m.app
        self.f = m.app.font
        self.root = DirectFrame(parent=self.app.aspect2d, frameColor=PANEL_BG, frameSize=(-w, w, -h, h))
        self.w, self.h = w, h
        self.items = []
        self.text(self.title, (-w + 0.06, h - 0.1), 0.07, H.ACCENT, TextNode.ALeft, keep=True)
        self.cash = self.text("", (w - 0.2, h - 0.1), 0.06, H.GOLD, TextNode.ARight, keep=True)
        self.button("X", (w - 0.08, h - 0.085), self.m.close_panel, 0.09, 0.08, keep=True)
        self.refresh()

    def text(self, s, pos, scale=0.045, fg=H.WHITE, align=TextNode.ALeft, keep=False, wrap=None):
        t = OnscreenText(parent=self.root, text=s, pos=pos, scale=scale, fg=fg, align=align, font=self.f, mayChange=True,
                         wordwrap=wrap)
        if not keep:
            self.items.append(t)
        return t

    def button(self, s, pos, cmd, w=0.3, h=0.075, hot=False, enabled=True, keep=False, scale=0.042):
        def go():
            self.app.sounds.play("click", 0.5)
            cmd()
        b = DirectButton(parent=self.root, text=s, pos=(pos[0], 0, pos[1]), scale=scale, command=go if enabled else None,
                         text_font=self.f, frameColor=BTN_HOT if (hot and enabled) else BTN,
                         text_fg=(0.1, 0.07, 0.03, 1) if (hot and enabled) else (H.WHITE if enabled else H.MUTED),
                         relief=DGG.FLAT, pressEffect=0,
                         frameSize=(-w / 2 / scale, w / 2 / scale, -h / 2 / scale + 0.3, h / 2 / scale + 0.3))
        if not keep:
            self.items.append(b)
        return b

    def clear(self):
        for i in self.items:
            i.destroy()
        self.items = []

    def refresh(self):
        self.clear()
        self.cash.setText(f"${self.m.cash():,}")
        self.build()

    def build(self):
        pass

    def update(self, dt):
        pass

    def destroy(self):
        self.clear()
        self.root.destroy()


# ---------------------------------------------------------------------------- 3D views inside panels
class View3D:
    """A little 3D scene rendered into a texture and shown as an image in a panel (so buttons can sit on top)."""

    def __init__(self, app, rect, px=640, fov=30, bg=(0.12, 0.11, 0.1, 1), dist=4.2):
        from . import geom as G
        from .world import make_lights
        x0, x1, y0, y1 = rect
        self.app, self.rect = app, rect
        self.scene = NodePath("view3d")
        G.shader_auto(self.scene)
        make_lights(self.scene, "#fff2e0", "#7a8090", shadows=False)
        self.holder = self.scene.attachNewNode("holder")
        self.inner = self.holder.attachNewNode("inner")
        h_px = max(64, int(px * (y1 - y0) / (x1 - x0)))
        self.buf = app.win.makeTextureBuffer("view3d", px, h_px)
        self.buf.setClearColor(bg)
        self.buf.setSort(-10)
        self.lens = PerspectiveLens()
        self.lens.setFov(fov, fov * (y1 - y0) / (x1 - x0))
        self.cam = app.makeCamera(self.buf, lens=self.lens)
        self.cam.reparentTo(self.scene)
        self.cam.setPos(0, -dist, 0)
        self.cam.lookAt(0, 0, 0)
        self.frame = None

    def show_in(self, parent):
        x0, x1, y0, y1 = self.rect
        self.frame = DirectFrame(parent=parent, frameColor=(1, 1, 1, 1), frameSize=(x0, x1, y0, y1),
                                 image=self.buf.getTexture(), image_scale=((x1 - x0) / 2, 1, (y1 - y0) / 2),
                                 image_pos=((x0 + x1) / 2, 0, (y0 + y1) / 2))
        return self.frame

    def clear(self):
        self.inner.getChildren().detach()

    def fit(self, node, size_target=1.6):
        c, size = bounds_center(node)
        self.inner.setPos(-c[0], -c[1], -c[2])
        self.holder.setScale(size_target / size)

    def to_panel(self, node, pt):
        """Panel (aspect2d) position of a 3D point given in node's space, or None if it is off screen."""
        from panda3d.core import Point2, Point3
        p = self.cam.getRelativePoint(node, Point3(*pt))
        film = Point2()
        if not self.lens.project(p, film):
            return None
        x0, x1, y0, y1 = self.rect
        return x0 + (film.x + 1) / 2 * (x1 - x0), y0 + (film.y + 1) / 2 * (y1 - y0)

    def destroy(self):
        if self.frame:
            self.frame.destroy()
        self.app.graphicsEngine.removeWindow(self.buf)
        self.scene.removeNode()


def part_node(parent, part, parts):
    """3D model of a single part (receivers use the real gun model when installed)."""
    if part["slot"] == "receiver":
        g, _ = build_gun(parent, {"receiver": part["id"]}, parts)
        return g
    from .geom import build_part
    return build_part(parent, part)


def part_lines(p):
    return [x for x in part_summary(p).split("   ") if x]


SLOT_SHORT = {"receiver": "Receiver", "barrel": "Barrel", "magazine": "Mag", "stock": "Stock", "grip": "Grip",
              "sight": "Scope", "muzzle": "Muzzle", "bayonet": "Bayonet"}


# ---------------------------------------------------------------------------- supplier
class SupplierPanel(Panel):
    title = "SUPPLIER"
    CARD_X = (-0.9, -0.3, 0.3, 0.9)
    IMG_Y = (0.06, 0.5)

    def __init__(self, m):
        self.tab = "receiver"
        self.views = []
        self.shown = [None] * 4
        self.t = 0.0
        super().__init__(m)
        for cx in self.CARD_X:
            v = View3D(self.app, (cx - 0.28, cx + 0.28, self.IMG_Y[0], self.IMG_Y[1]), px=360, bg=(0.14, 0.15, 0.18, 1))
            v.show_in(self.root)
            v.frame.hide()
            self.views.append(v)
        self.refresh()

    def set_tab(self, slot):
        self.tab = slot
        self.refresh()

    def offers(self):
        return [(i, off) for i, off in enumerate(self.m.inv.get("stock", [])) if off and off.get("slot") == self.tab]

    def build(self):
        parts = self.m.parts
        x = -1.08
        for s in SLOTS:
            n = sum(1 for off in self.m.inv.get("stock", []) if off and off.get("slot") == s["id"] and not off.get("sold"))
            self.button(f"{SLOT_SHORT[s['id']]} ({n})", (x, 0.62), lambda sid=s["id"]: self.set_tab(sid), 0.27, 0.075,
                        hot=self.tab == s["id"], scale=0.034)
            x += 0.31
        offers = self.offers()
        for k, cx in enumerate(self.CARD_X):
            v = self.views[k] if k < len(self.views) else None
            if k >= len(offers):
                if v:
                    v.frame.hide()
                    v.clear()
                    self.shown[k] = None
                continue
            i, off = offers[k]
            p = parts.get(off["pid"])
            if not p:
                continue
            rc = hexc(RARITY_COLORS[p["tier"]])
            bar = DirectFrame(parent=self.root, frameColor=rc, frameSize=(cx - 0.28, cx + 0.28, 0.5, 0.515))
            self.items.append(bar)
            if v:
                v.frame.show()
                if self.shown[k] != off["pid"]:
                    v.clear()
                    node = part_node(v.inner, p, parts)
                    v.fit(node, 1.25 if p["slot"] == "receiver" else 1.0)
                    self.shown[k] = off["pid"]
            self.text(p["name"], (cx, 0.0), 0.042, rc, TextNode.ACenter)
            self.text(f"{RARITY[p['tier']]} {SLOT_SHORT[p['slot']].lower()}", (cx, -0.05), 0.03, H.MUTED, TextNode.ACenter)
            for j, line in enumerate(part_lines(p)[:4]):
                self.text(line, (cx, -0.11 - j * 0.045), 0.03, H.WHITE, TextNode.ACenter)
            self.text(p.get("description", ""), (cx, -0.32), 0.027, H.MUTED, TextNode.ACenter, wrap=18)
            if off.get("sold"):
                self.text("SOLD", (cx, -0.47), 0.05, H.MUTED, TextNode.ACenter)
            else:
                have = self.m.inv.get("parts", {}).get(off["pid"], 0)
                self.button(f"Buy  ${off['price']}", (cx, -0.47), lambda i=i: self.m.act({"a": "buy_part", "i": i}),
                            0.4, 0.085, hot=True, enabled=self.m.cash() >= off["price"])
                if have:
                    self.text(f"you have {have}", (cx, -0.56), 0.028, H.MUTED, TextNode.ACenter)
        if not offers:
            self.text("Nothing in this category today.", (0, 0.2), 0.045, H.MUTED, TextNode.ACenter)
        self.text("New stock arrives every time you visit the town plaza and come back.", (0, -0.66), 0.032, H.MUTED,
                  TextNode.ACenter)
        owned = sum(self.m.inv.get("parts", {}).values())
        self.text(f"Parts in your workshop: {owned}", (0, -0.73), 0.032, H.MUTED, TextNode.ACenter)

    def update(self, dt):
        self.t += dt
        for v in self.views:
            v.holder.setHpr(90 + self.t * 40, 8, 0)

    def destroy(self):
        for v in self.views:
            v.destroy()
        super().destroy()


# ---------------------------------------------------------------------------- workbench: hands-on assembly
SCREWS = {"receiver": 0, "barrel": 2, "magazine": 1, "stock": 2, "grip": 2, "sight": 2, "muzzle": 1, "bayonet": 1}
TURNS = 3


class WorkbenchPanel(Panel):
    """Put a receiver on the bench, attach parts one by one, then tighten every screw before the gun is done."""
    title = "WORKBENCH  -  assemble by hand"
    refresh_on_players = False
    VIEW = (-0.42, 1.2, -0.14, 0.68)

    def __init__(self, m):
        self.placed = {}
        self.turns = {}           # slot -> [turns per screw]
        self.nodes = {}           # slot -> part NodePath
        self.fly = {}             # slot -> seconds since attached (fly-in animation)
        self.screw_btns = []
        self.name = ""
        self.t = 0.0
        self.target_pos, self.target_scale = None, None
        self.view = View3D(m.app, self.VIEW, px=900, bg=(0.16, 0.14, 0.12, 1))
        super().__init__(m)
        self.view.show_in(self.root)
        self.refresh()

    # ---- helpers
    def owned_ids(self, slot):
        parts = self.m.parts
        out = [pid for pid, n in self.m.inv.get("parts", {}).items() if n > 0 and parts.get(pid, {}).get("slot") == slot]
        out.sort(key=lambda q: (parts[q]["tier"], parts[q]["name"]))
        return out

    def fastened(self, slot):
        return all(t >= TURNS for t in self.turns.get(slot, []))

    def ready(self):
        return all(self.placed.get(s["id"]) for s in SLOTS if s["required"]) and all(self.fastened(s) for s in self.placed)

    def reset(self):
        self.placed.clear()
        self.turns.clear()
        self.fly.clear()
        self.relayout()
        self.refresh()

    # ---- actions
    def pick(self, slot, pid):
        if slot != "receiver" and not self.placed.get("receiver"):
            self.m.hud.show_toast("Put a receiver on the bench first", True)
            self.app.sounds.play("gate_bad", 0.4)
            return
        if self.placed.get(slot) == pid:          # click the part again to take it off
            self.placed.pop(slot)
            self.turns.pop(slot, None)
            if slot == "receiver":
                self.placed.clear()
                self.turns.clear()
            self.app.sounds.play("tick", 0.5)
        else:
            self.placed[slot] = pid
            self.turns[slot] = [0] * SCREWS.get(slot, 1)
            self.fly[slot] = 0.0
            self.app.sounds.play("craft", 0.45)
        self.relayout()
        self.refresh()

    def turn(self, slot, k):
        tl = self.turns.get(slot)
        if not tl or tl[k] >= TURNS or self.fly.get(slot, 1) < 0.35:
            return
        tl[k] += 1
        self.app.sounds.play("tick", 0.7)
        if self.fastened(slot):
            self.app.sounds.play("gate_good", 0.5)
            self.refresh()
        self.place_screws()

    def finish(self):
        if not self.ready():
            return
        self.name = self.entry.get().strip()
        self.m.act({"a": "craft", "parts": dict(self.placed), "name": self.name})
        self.app.sounds.play("craft", 0.8)

    # ---- 3D
    def relayout(self):
        from .geom import add_shape, gun_layout
        parts = self.m.parts
        for n in self.nodes.values():
            n.removeNode()
        self.nodes = {}
        res = gun_layout(self.placed, parts) if self.placed.get("receiver") else None
        if not res:
            self.target_pos = None
            return
        lay, _ = res
        for p, off in lay:
            n = self.view.inner.attachNewNode("part_" + p["slot"])
            for sh in p.get("model", []):
                add_shape(n, sh)
            n.setPos(*off)
            n.setPythonTag("home", off)
            self.nodes[p["slot"]] = n
        a, b = self.view.inner.getTightBounds(self.view.inner)
        size = max(b[0] - a[0], b[1] - a[1], b[2] - a[2], 1e-3)
        self.target_pos = (-(a[0] + b[0]) / 2, -(a[1] + b[1]) / 2, -(a[2] + b[2]) / 2)
        self.target_scale = 1.55 / max(0.35, size)
        if self.view.holder.getScale()[0] == 1.0:
            self.view.inner.setPos(*self.target_pos)
            self.view.holder.setScale(self.target_scale)

    def screw_points(self, slot):
        n = self.nodes.get(slot)
        if n is None:
            return []
        a, b = n.getTightBounds(n) or ((0, 0, 0), (0, 0, 0))
        k = len(self.turns.get(slot, []))
        pts = []
        for i in range(k):
            f = (i + 1) / (k + 1)
            y = a[1] + (b[1] - a[1]) * f
            z = (a[2] + b[2]) / 2
            pts.append((a[0], y, z))       # the side facing the camera
        return pts

    def place_screws(self):
        for btn in self.screw_btns:
            btn.destroy()
        self.screw_btns = []
        for slot, tl in self.turns.items():
            pts = self.screw_points(slot)
            for k, pt in enumerate(pts):
                if k >= len(tl):
                    break
                done = tl[k] >= TURNS
                col = [(0.9, 0.25, 0.2, 0.95), (1.0, 0.55, 0.15, 0.95), (1.0, 0.85, 0.2, 0.95), (0.35, 0.85, 0.4, 0.9)][min(3, tl[k])]
                b = DirectButton(parent=self.root, text="+", text_scale=0.05, text_fg=(0.1, 0.08, 0.05, 1), relief=DGG.FLAT,
                                 frameColor=col, frameSize=(-0.028, 0.028, -0.028, 0.028), pressEffect=0, text_pos=(0, -0.016),
                                 command=(lambda s=slot, i=k: self.turn(s, i)) if not done else None)
                b.setR(tl[k] * 30)
                b.setPythonTag("at", (slot, pt))
                self.screw_btns.append(b)
        self.update_screws()

    def update_screws(self):
        for b in self.screw_btns:
            slot, pt = b.getPythonTag("at")
            n = self.nodes.get(slot)
            pos = self.view.to_panel(n, pt) if n is not None else None
            if pos is None or self.fly.get(slot, 1) < 0.35:
                b.hide()
            else:
                b.show()
                b.setPos(pos[0], 0, pos[1])

    # ---- UI
    def refresh(self):
        e = getattr(self, "entry", None)
        if e is not None:
            try:
                self.name = e.get()
            except Exception:
                pass
        inv = self.m.inv.get("parts", {})
        used = {}
        for s, pid in list(self.placed.items()):
            used[pid] = used.get(pid, 0) + 1
            if inv.get(pid, 0) < used[pid]:      # part no longer owned (sold, used up)
                self.placed.pop(s)
                self.turns.pop(s, None)
        if not self.placed.get("receiver") and self.placed:
            self.placed.clear()
            self.turns.clear()
        if getattr(self, "view", None) and set(self.placed) != set(self.nodes):
            self.relayout()
        super().refresh()
        if getattr(self, "view", None):
            self.place_screws()

    def build(self):
        parts = self.m.parts
        if not hasattr(self, "placed"):
            return
        y = 0.66
        for s in SLOTS:
            sid = s["id"]
            p = parts.get(self.placed.get(sid, ""))
            state = ""
            if p:
                state = "  [fastened]" if self.fastened(sid) else "  [tighten screws]"
            self.text(s["name"].upper() + ("" if s["required"] else " (opt)") + state, (-1.19, y), 0.028,
                      H.GOOD if p and self.fastened(sid) else (H.GOLD if p else H.MUTED))
            opts = self.owned_ids(sid)
            if not opts:
                self.text("buy at the supplier" if s["required"] else "-", (-1.19, y - 0.06), 0.028, H.MUTED)
            for j, pid in enumerate(opts[:3]):
                q = parts[pid]
                n = self.m.inv.get("parts", {}).get(pid, 0)
                on = self.placed.get(sid) == pid
                b = self.button(f"{q['name'][:13]}{' x' + str(n) if n > 1 else ''}", (-1.07 + j * 0.25, y - 0.05),
                                lambda sid=sid, pid=pid: self.pick(sid, pid), 0.24, 0.06, hot=on, scale=0.024)
                if not on:
                    b["text_fg"] = hexc(RARITY_COLORS[q["tier"]])
            y -= 0.135
        if not self.placed.get("receiver"):
            self.text("Pick a RECEIVER on the left to put it on the bench.", (0.39, 0.25), 0.04, H.WHITE, TextNode.ACenter, wrap=26)
        # stats + finish
        lo = {s: pid for s, pid in self.placed.items()}
        if self.placed.get("receiver"):
            st = compute_stats(lo, parts)
            self.text(gun_summary(st), (0.39, -0.2), 0.03, H.WHITE, TextNode.ACenter)
            loose = sum(1 for s in self.turns for t in self.turns[s] if t < TURNS)
            missing = [s["name"].lower() for s in SLOTS if s["required"] and not self.placed.get(s["id"])]
            if missing:
                msg, col = "Still needs a " + " and a ".join(missing), H.MUTED
            elif loose:
                msg, col = f"Tighten {loose} more screw{'s' if loose != 1 else ''}: click each one {TURNS} times", H.GOLD
            else:
                msg, col = f"Ready!  Parts worth ${gun_value(lo, parts)} - try selling for ${int(gun_value(lo, parts) * 1.3)}", H.GOOD
            self.text(msg, (0.39, -0.27), 0.032, col, TextNode.ACenter)
        self.text("Name", (-0.4, -0.38), 0.03, H.MUTED)
        self.entry = DirectEntry(parent=self.root, initialText=self.name, pos=(-0.3, 0, -0.385), scale=0.038, width=11,
                                 numLines=1, entryFont=self.f, text_fg=H.WHITE, frameColor=(0.12, 0.13, 0.16, 1),
                                 relief=DGG.FLAT, command=lambda t: None)
        self.items.append(self.entry)
        self.button("FINISH GUN", (0.92, -0.375), self.finish, 0.42, 0.09, hot=True, enabled=self.ready())
        self.button("Clear bench", (0.47, -0.375), self.reset, 0.3, 0.07, scale=0.032)
        guns = self.m.inv.get("guns", [])
        dis = bool(self.m.inv.get("effects", {}).get("disassemble"))
        self.text("YOUR GUNS" + ("" if dis else "   (upgrade the workbench to scrap guns back into parts)"), (-1.19, -0.5), 0.03, H.MUTED)
        for i, g in enumerate(guns[:6]):
            x = -1.19 + (i % 3) * 0.8
            yy = -0.58 - (i // 3) * 0.11
            held = g["id"] == self.m.inv.get("held")
            self.text(("* " if held else "") + g["name"][:13] + f" {g.get('cond', 1) * 100:.0f}%", (x, yy), 0.032, H.GOLD if held else H.WHITE)
            self.button("Hold", (x + 0.5, yy + 0.012), lambda g=g: self.m.act({"a": "hold", "gid": g["id"]}), 0.13, 0.06, scale=0.032)
            if dis:
                self.button("Scrap", (x + 0.65, yy + 0.012), lambda g=g: self.m.act({"a": "disassemble", "gid": g["id"]}), 0.14, 0.06, scale=0.032)

    def update(self, dt):
        self.t += dt
        v = self.view
        v.holder.setH(90 + math.sin(self.t * 0.5) * 14)
        v.holder.setP(math.sin(self.t * 0.37) * 5)
        if self.target_pos is not None:
            k = min(1.0, dt * 6)
            cur = v.inner.getPos()
            v.inner.setPos(cur + (Vec3(*self.target_pos) - cur) * k)
            s = v.holder.getScale()[0]
            v.holder.setScale(s + (self.target_scale - s) * k)
        for slot, t in list(self.fly.items()):
            t += dt
            self.fly[slot] = t
            n = self.nodes.get(slot)
            if n is not None:
                hx, hy, hz = n.getPythonTag("home")
                f = min(1.0, t / 0.35)
                e = 1 - (1 - f) ** 3
                n.setPos(hx - 0.25 * (1 - e), hy, hz + 0.3 * (1 - e))
                n.setR(25 * (1 - e))
            if t > 0.35:
                self.fly.pop(slot)
                if n is not None:
                    n.setPos(*n.getPythonTag("home"))
                    n.setR(0)
                self.update_screws()
        self.update_screws()

    def destroy(self):
        for b in self.screw_btns:
            b.destroy()
        self.view.destroy()
        super().destroy()


# ---------------------------------------------------------------------------- shelves
class ShelfPanel(Panel):
    def __init__(self, m, slot):
        self.slot = slot
        self.pick = None
        self.price = None
        self.title = f"SHELF {slot + 1}"
        super().__init__(m, 1.0, 0.7)

    def build(self):
        info = self.m.infos.get(self.m.me, {})
        shelf = info.get("shelf", [])
        item = shelf[self.slot] if self.slot < len(shelf) else None
        if self.slot >= info.get("slots", 3):
            self.text("This shelf is locked - buy Display Racks at the upgrade board.", (0, 0), 0.045, H.MUTED, TextNode.ACenter)
            return
        if item:
            g = item["gun"]
            st = compute_stats(g["parts"], self.m.parts)
            self.text(g["name"], (-0.94, 0.45), 0.06, H.GOLD)
            self.text(gun_summary(st), (-0.94, 0.37), 0.032, H.MUTED)
            self.text(f"Parts worth ${g['value']}   -   {g.get('cond', 1) * 100:.0f}% clean", (-0.94, 0.3), 0.036)
            if self.price is None:
                self.price = item["price"]
            self.price_ui(0.1)
            self.button("Update price", (-0.35, -0.25), lambda: self.m.act({"a": "reprice", "slot": self.slot, "price": self.price}), 0.42, 0.09, hot=True)
            self.button("Take back", (0.25, -0.25), lambda: self.m.act({"a": "unshelve", "slot": self.slot}), 0.36, 0.09)
            return
        guns = self.m.inv.get("guns", [])
        if not guns:
            self.text("You have no guns. Build one at the workbench!", (0, 0.2), 0.045, H.MUTED, TextNode.ACenter)
            return
        self.text("Pick a gun to put on display:", (-0.94, 0.48), 0.04, H.MUTED)
        if self.pick not in [g["id"] for g in guns]:
            self.pick = guns[-1]["id"]
            self.price = None
        for i, g in enumerate(guns[:6]):
            y = 0.38 - i * 0.085
            on = g["id"] == self.pick
            self.button(("> " if on else "") + f"{g['name']}   (worth ${g['value']}, {g.get('cond', 1) * 100:.0f}% clean)", (-0.35, y), lambda g=g: self.choose(g), 1.15, 0.07,
                        hot=on, scale=0.036)
        g = next(g for g in guns if g["id"] == self.pick)
        if self.price is None:
            self.price = int(g["value"] * 1.3)
        self.price_ui(-0.2)
        self.button("Put on shelf", (0, -0.5), lambda: self.m.act({"a": "shelve", "slot": self.slot, "gid": self.pick, "price": self.price}),
                    0.5, 0.09, hot=True)

    def choose(self, g):
        self.pick = g["id"]
        self.price = int(g["value"] * 1.3)
        self.refresh()

    def price_ui(self, y):
        self.text("Price", (-0.94, y), 0.04, H.MUTED)
        self.text(f"${self.price}", (0, y - 0.01), 0.07, H.GOLD, TextNode.ACenter)
        for i, d in enumerate((-50, -10, 10, 50)):
            x = [-0.62, -0.34, 0.34, 0.62][i]
            self.button(f"{'+' if d > 0 else ''}{d}", (x, y), lambda d=d: self.bump(d), 0.2, 0.07)

    def bump(self, d):
        self.price = max(1, (self.price or 0) + d)
        self.refresh()


class RivalShelfPanel(Panel):
    def __init__(self, m, owner, slot):
        self.owner, self.slot = owner, slot
        self.title = "RIVAL SHELF"
        super().__init__(m, 0.95, 0.5)

    def build(self):
        o = self.m.infos.get(self.owner, {})
        shelf = o.get("shelf", [])
        item = shelf[self.slot] if self.slot < len(shelf) else None
        if not item:
            self.text("Sold out!", (0, 0), 0.06, H.MUTED, TextNode.ACenter)
            return
        g = item["gun"]
        st = compute_stats(g["parts"], self.m.parts)
        self.text(g["name"], (-0.88, 0.25), 0.065, H.GOLD)
        self.text(f"Sold by {o.get('name', '?')}", (-0.88, 0.17), 0.038, H.MUTED)
        self.text(gun_summary(st), (-0.88, 0.08), 0.031)
        can = self.m.cash() >= item["price"]
        self.button(f"Buy for ${item['price']}", (0, -0.2), lambda: self.m.act({"a": "buy_gun", "owner": self.owner, "slot": self.slot}),
                    0.6, 0.1, hot=True, enabled=can)
        if not can:
            self.text("Not enough cash", (0, -0.33), 0.04, H.BAD, TextNode.ACenter)


# ---------------------------------------------------------------------------- upgrades
class UpgradePanel(Panel):
    title = "SHOP UPGRADES"

    def build(self):
        info = self.m.infos.get(self.m.me, {})
        mine = info.get("upgrades", {})
        for i, u in enumerate(list(self.m.content.get("upgrades", {}).values())[:7]):
            y = 0.58 - i * 0.2
            lvl = mine.get(u["id"], 0)
            levels = u.get("levels", [])
            self.text(u.get("name", u["id"]), (-1.19, y), 0.05, H.WHITE)
            pips = "".join("#" if j < lvl else "-" for j in range(len(levels)))
            self.text(f"[{pips}]", (-0.55, y), 0.045, H.ACCENT)
            self.text(u.get("description", ""), (-1.19, y - 0.06), 0.032, H.MUTED, wrap=40)
            if lvl < len(levels):
                cost = levels[lvl]["cost"]
                self.button(f"Level {lvl + 1}:  ${cost}", (0.95, y - 0.02), lambda u=u: self.m.act({"a": "upgrade", "id": u["id"]}),
                            0.42, 0.09, hot=True, enabled=self.m.cash() >= cost)
            else:
                self.text("MAX", (0.95, y - 0.03), 0.05, H.GOOD, TextNode.ACenter)


# ---------------------------------------------------------------------------- market stalls
class VendorPanel(Panel):
    def __init__(self, m, vendor):
        self.vendor = vendor
        self.title = vendor["name"].upper()
        super().__init__(m, 1.0, 0.72)

    def build(self):
        items = self.m.content.get("items", {})
        mine = self.m.inv.get("items", {})
        y = 0.45
        for iid in self.vendor["items"]:
            it = items.get(iid)
            if not it:
                continue
            desc = {"food": f"+{it['value']} food", "drink": f"+{it['value']} energy", "heal": f"+{it['value']} health",
                    "armor": f"{it['value']} shields (worn right away)", "tool": "cleans one gun"}.get(it["kind"], "")
            have = f"   (you have {mine.get(iid, 0)})" if it["kind"] != "armor" else ""
            self.text(it["name"], (-0.94, y), 0.05, H.WHITE)
            self.text(desc + have, (-0.94, y - 0.055), 0.034, H.MUTED)
            self.button(f"${it['price']}", (0.75, y - 0.015),
                        lambda iid=iid: self.m.act({"a": "buy_item", "vendor": self.vendor["id"], "item": iid}),
                        0.26, 0.08, hot=True, enabled=self.m.cash() >= it["price"])
            y -= 0.17
        self.text("Use items from your inventory (I), or quick-use: H heal, G eat", (0, -0.62), 0.035, H.MUTED, TextNode.ACenter)


class ContractPanel(Panel):
    """The Collector's special orders: build a gun that meets every requirement, hold it, deliver it."""
    title = "THE COLLECTOR - SPECIAL ORDERS"

    def __init__(self, m):
        super().__init__(m, 1.15, 0.8)

    def build(self):
        from ..gun import compute_stats
        m = self.m
        guns = m.inv.get("guns", [])
        held = next((g for g in guns if g["id"] == m.inv.get("held")), None)
        st = compute_stats(held["parts"], m.parts) if held else None
        self.text(f"Holding: {held['name']}  ({held.get('cond', 1) * 100:.0f}% condition)" if held else "Hold a gun to check it",
                  (0, 0.64), 0.04, H.MUTED, TextNode.ACenter)
        if not m.contracts:
            self.text("No orders today. Come back tomorrow morning.", (0, 0.2), 0.05, H.MUTED, TextNode.ACenter)
        y = 0.52
        for c in m.contracts:
            done = c.get("done")
            self.text(c["title"], (-1.08, y), 0.055, H.MUTED if done else H.WHITE)
            self.text(f"${c['reward']}", (1.08, y), 0.06, H.MUTED if done else H.GOLD, TextNode.ARight)
            y -= 0.075
            all_ok = bool(st) and held.get("cond", 1) >= c.get("minCond", 0)
            for r in c["reqs"]:
                v = st.get(r["stat"], 0) if st else None
                good = st is not None and ((r["op"] == ">" and v >= r["value"] - 1e-6) or (r["op"] == "<" and v <= r["value"] + 1e-6)
                                           or (r["op"] == "=" and abs(v - r["value"]) < 1e-6))
                all_ok = all_ok and good
                need = "yes" if r["stat"] == "auto" else (f"at least {r['value']:g}" if r["op"] == ">" else f"at most {r['value']:g}")
                have = "" if st is None else ("  (yours: " + ("yes" if r["stat"] == "auto" and v else "no" if r["stat"] == "auto" else f"{v:.3g}") + ")")
                self.text(("[OK] " if good else "[  ] ") + f"{r['label']}: {need}{have}", (-1.0, y), 0.04,
                          H.GOOD if good else (H.MUTED if done else H.BAD))
                y -= 0.06
            self.text(f"[{'OK' if held and held.get('cond', 1) >= c.get('minCond', 0) else '  '}] Condition {c.get('minCond', 0) * 100:.0f}%+",
                      (-1.0, y), 0.04, H.MUTED)
            if done:
                self.text(f"Filled by {done}", (0.75, y + 0.06), 0.045, H.MUTED, TextNode.ACenter)
            else:
                self.button("Deliver held gun", (0.75, y + 0.07), lambda cid=c["id"]: m.act({"a": "deliver", "contract": cid}),
                            0.5, 0.09, hot=True, enabled=all_ok)
            y -= 0.12
        self.text("First gunsmith to deliver gets paid. New orders every morning.", (0, -0.72), 0.035, H.MUTED, TextNode.ACenter)


class InventoryPanel(Panel):
    title = "INVENTORY"

    def build(self):
        items = self.m.content.get("items", {})
        mine = self.m.inv.get("items", {})
        y = 0.55
        if not mine:
            self.text("Nothing here. Buy food, medkits and cleaning kits at the market stalls.", (0, 0.2), 0.045, H.MUTED, TextNode.ACenter)
        for iid, n in sorted(mine.items()):
            it = items.get(iid)
            if not it:
                continue
            self.text(f"{it['name']}  x{n}", (-1.19, y), 0.05)
            if it["kind"] in ("food", "drink", "heal"):
                self.button("Use", (0.95, y + 0.012), lambda iid=iid: self.m.act({"a": "use_item", "item": iid}), 0.22, 0.075, hot=True)
            y -= 0.11
        guns = self.m.inv.get("guns", [])
        self.text("GUNS", (-1.19, -0.42), 0.035, H.MUTED)
        for i, g in enumerate(guns[:6]):
            c = g.get("cond", 1.0)
            col = H.GOOD if c >= 0.7 else (1, 0.8, 0.3, 1) if c >= 0.4 else H.BAD
            self.text(f"{g['name']}  -  {c * 100:.0f}% clean", (-1.19 + (i % 2) * 1.2, -0.5 - (i // 2) * 0.07), 0.04, col)


class CleaningPanel(Panel):
    """Scrub minigame: click the grime before it spreads. Clicking clean metal wastes the cleaning kit."""
    title = "CLEANING BENCH"
    refresh_on_players = False
    AREA = (-0.15, 1.2, -0.45, 0.55)   # aspect2d rect of the preview / scrub area

    def __init__(self, m):
        self.gid = None
        self.active = False
        self.left = 0
        self.cond = 0.0
        self.spots = []
        self.spot_btns = []
        self.t = 0.0
        self.scene = NodePath("cleanprev")
        from . import geom as G
        from .world import make_lights
        G.shader_auto(self.scene)
        make_lights(self.scene, "#fff2e0", "#7a8090", shadows=False)
        self.holder = self.scene.attachNewNode("holder")
        self.gun = None
        # render the gun into a texture shown inside the panel, so the grime spots can sit on top of it
        x0, x1, y0, y1 = self.AREA
        self.buf = m.app.win.makeTextureBuffer("cleanbuf", 768, int(768 * (y1 - y0) / (x1 - x0)))
        self.buf.setClearColor((0.12, 0.11, 0.1, 1))
        self.buf.setSort(-10)
        lens = PerspectiveLens()
        lens.setFov(30, 30 * (y1 - y0) / (x1 - x0))
        self.cam = m.app.makeCamera(self.buf, lens=lens)
        self.cam.reparentTo(self.scene)
        self.cam.setPos(0, -4.2, 0)
        self.cam.lookAt(0, 0, 0)
        self.lens = lens
        super().__init__(m)
        self.image = DirectFrame(parent=self.root, frameColor=(1, 1, 1, 1), frameSize=(x0, x1, y0, y1),
                                 image=self.buf.getTexture(), image_scale=((x1 - x0) / 2, 1, (y1 - y0) / 2),
                                 image_pos=((x0 + x1) / 2, 0, (y0 + y1) / 2))

    def build(self):
        guns = self.m.inv.get("guns", [])
        kits = self.m.inv.get("items", {}).get("cleaning_kit", 0)
        self.text(f"Cleaning kits: {kits}", (-1.19, 0.6), 0.045, H.GOLD if kits else H.BAD)
        self.text("Dirty guns jam, shoot wider and sell for less.", (-1.19, 0.53), 0.033, H.MUTED)
        self.text("Customers won't touch anything under 30%.", (-1.19, 0.48), 0.033, H.MUTED)
        y = 0.36
        for g in guns[:7]:
            c = g.get("cond", 1.0)
            on = g["id"] == self.gid
            self.button(f"{g['name'][:14]}  {c * 100:.0f}%", (-0.75, y), lambda g=g: self.pick(g), 0.8, 0.075, hot=on, scale=0.036)
            y -= 0.1
        if not self.active:
            g = next((g for g in guns if g["id"] == self.gid), None)
            self.button("Start cleaning (uses 1 kit)", (-0.75, -0.5), self.start, 0.8, 0.09, hot=True,
                        enabled=bool(g and kits and g.get("cond", 1) < 0.999))
            self.text("Click the grime as fast as you can.\nSpots you leave alone spread.\nClicking clean metal wastes the kit.",
                      (0.52, -0.6), 0.034, H.MUTED, TextNode.ACenter)
        else:
            self.text(f"Scrubs left: {self.left}", (0.1, -0.55), 0.05, H.WHITE)
            self.text(f"Condition: {self.cond * 100:.0f}%", (0.75, -0.55), 0.05, H.GOOD if self.cond >= 0.7 else H.WHITE)
            self.button("Stop", (1.05, -0.68), self.stop, 0.2, 0.07)

    def pick(self, g):
        if not self.active:
            self.gid = g["id"]
            self.cond = g.get("cond", 1.0)
            self.show_gun(g)
            self.refresh()

    def show_gun(self, g):
        if self.gun:
            self.gun.removeNode()
        gun, _ = build_gun(self.holder, g["parts"], self.m.parts)
        c, size = bounds_center(gun)
        gun.setPos(-c[0], -c[1], -c[2])
        self.holder.setScale(1.6 / size)
        self.gun = gun

    def start(self):
        if self.gid:
            self.m.act({"a": "clean_start", "gid": self.gid})

    def stop(self):
        self.m.act({"a": "clean_stop"})
        self.end()

    def end(self):
        self.active = False
        for b in self.spot_btns:
            b.destroy()
        self.spot_btns = []
        self.spots = []
        self.refresh()

    JOB = False

    def on_server(self, msg):
        if bool(msg.get("job")) != self.JOB:
            return
        self.gid = msg["gid"]
        self.cond = msg["cond"]
        was = self.active
        self.left = msg["left"]
        self.active = msg["left"] > 0 and msg["cond"] < 0.999
        if self.active and not was:
            self.catcher()
            for _ in range(4):
                self.spawn_spot()
            self.app.sounds.play("craft", 0.5)
        if was and not self.active:
            self.app.sounds.play("gate_good", 0.7)
            self.end()
            return
        self.refresh()

    def refresh(self):
        super().refresh()
        for b in self.spot_btns:      # keep the scrub spots above the rebuilt panel widgets
            b.reparentTo(self.root)

    def catcher(self):
        x0, x1, y0, y1 = self.AREA
        b = DirectButton(parent=self.root, frameColor=(0, 0, 0, 0.01), frameSize=(x0, x1, y0, y1), relief=DGG.FLAT,
                         command=self.miss, pressEffect=0)
        self.spot_btns.append(b)

    def spawn_spot(self):
        import random
        x0, x1, y0, y1 = self.AREA
        sx, sy = random.uniform(x0 + 0.15, x1 - 0.15), random.uniform(y0 + 0.2, y1 - 0.15)
        spot = {"x": sx, "y": sy, "hp": random.randint(1, 2), "age": 0.0}
        btn = DirectButton(parent=self.root, pos=(sx, 0, sy), relief=DGG.FLAT, pressEffect=0,
                           frameColor=(0.24, 0.17, 0.08, 0.92), frameSize=(-0.05, 0.05, -0.05, 0.05),
                           command=lambda: self.scrub(spot))
        spot["btn"] = btn
        self.spots.append(spot)
        self.spot_btns.append(btn)
        self.size_spot(spot)

    def size_spot(self, spot):
        s = 0.035 + 0.018 * spot["hp"]
        spot["btn"]["frameSize"] = (-s, s, -s, s)

    def scrub(self, spot):
        if not self.active or spot not in self.spots:
            return
        self.m.act({"a": "scrub"})
        self.app.sounds.play("tick", 0.6)
        spot["hp"] -= 1
        if spot["hp"] <= 0:
            self.spots.remove(spot)
            spot["btn"].destroy()
            self.spot_btns.remove(spot["btn"])
            self.spawn_spot()
        else:
            self.size_spot(spot)

    def miss(self):
        if self.active:
            self.m.act({"a": "miss"})
            self.app.sounds.play("gate_bad", 0.4)

    def update(self, dt):
        import random
        self.t += dt
        if self.gun:
            self.holder.setH(90 + math.sin(self.t * 0.6) * 10)
        if self.active:
            for spot in list(self.spots):
                spot["age"] += dt
                if spot["age"] > 2.2:          # grime spreads if you're slow
                    spot["age"] = 0.0
                    if spot["hp"] < 4:
                        spot["hp"] += 1
                        self.size_spot(spot)
                    elif len(self.spots) < 9 and random.random() < 0.6:
                        self.spawn_spot()

    def destroy(self):
        if self.active:
            self.m.act({"a": "clean_stop"})
        self.app.graphicsEngine.removeWindow(self.buf)
        self.scene.removeNode()
        super().destroy()


class ServicePanel(CleaningPanel):
    """Service window: clients queue outside with dirty guns. Clean one up to their target condition and get paid.
    No cleaning kit needed (they pay for your time), but missed clicks still waste scrubs - run out and they leave unpaid."""
    title = "SERVICE WINDOW  -  clean clients' guns"

    def __init__(self, m):
        self.target = 0.0
        self.shown_job = None
        self.job_cid = None
        super().__init__(m)

    def front(self):
        return next((j for j in self.m.jobs if j.get("front")), None)

    def build(self):
        jobs = self.m.jobs
        if not self.active:
            if not jobs:
                self.text("No clients waiting.", (-1.19, 0.58), 0.045, H.MUTED)
                self.text("Some townspeople bring dirty guns to this window.\nClean them up to the condition they ask for\nand they pay you on the spot.",
                          (-1.19, 0.48), 0.033, H.MUTED)
            y = 0.58
            for j in jobs[:3]:
                g = j["gun"]
                col = H.WHITE if j["front"] else H.MUTED
                self.text(f"{j['name']}  -  {g['name']}", (-1.19, y), 0.042, col)
                self.text(f"{g['cond'] * 100:.0f}%  ->  {j['target'] * 100:.0f}%      pays ${j['pay']}", (-1.19, y - 0.06), 0.036,
                          H.GOLD if j["front"] else H.MUTED)
                self.text(f"waits {j['patience']:.0f}s more" if not j.get("served") else "being served", (-1.19, y - 0.11), 0.03, H.MUTED)
                y -= 0.2
            fj = self.front()
            if fj and self.shown_job != fj["cid"]:
                self.shown_job = fj["cid"]
                self.show_gun(fj["gun"])
                self.cond = fj["gun"]["cond"]
            self.button("Take the job (front client)", (-0.75, -0.5), self.start, 0.8, 0.09, hot=True, enabled=bool(fj))
            self.text("Click the grime as fast as you can.\nReach their target before you run out of scrubs.\nClicking clean metal wastes 3 scrubs.",
                      (0.52, -0.6), 0.034, H.MUTED, TextNode.ACenter)
        else:
            self.text(f"Scrubs left: {self.left}", (0.1, -0.55), 0.05, H.WHITE)
            self.text(f"Condition: {self.cond * 100:.0f}%  /  target {self.target * 100:.0f}%", (0.6, -0.55), 0.045,
                      H.GOOD if self.cond >= self.target else H.WHITE)
            self.button("Give up", (1.05, -0.68), self.stop, 0.2, 0.07)

    def start(self):
        fj = self.front()
        if fj:
            self.job_cid = fj["cid"]
            self.m.act({"a": "job_take", "cid": fj["cid"]})

    JOB = True

    def on_server(self, msg):
        if not msg.get("job"):
            return
        self.target = msg.get("target", self.target)
        super().on_server(msg)
        if not self.active:
            self.shown_job = None
