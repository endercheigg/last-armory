"""Shop UIs: supplier terminal, workbench (with live 3D preview), shelves, rival shelves, upgrade board."""
from direct.gui.DirectGui import DGG, DirectButton, DirectEntry, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import Camera, NodePath, PerspectiveLens, TextNode

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


# ---------------------------------------------------------------------------- supplier
class SupplierPanel(Panel):
    title = "SUPPLIER  -  today's stock"

    def build(self):
        inv = self.m.inv
        parts = self.m.parts
        stock = inv.get("stock", [])
        for i, off in enumerate(stock[:12]):
            col, row = i % 2, i // 2
            x = -1.19 + col * 1.2
            y = 0.6 - row * 0.21
            if not off:
                self.text("- sold -", (x + 0.5, y - 0.05), 0.04, H.MUTED, TextNode.ACenter)
                continue
            p = parts.get(off["pid"])
            if not p:
                continue
            rc = hexc(RARITY_COLORS[p["tier"]])
            bar = DirectFrame(parent=self.root, frameColor=rc, frameSize=(x, x + 0.012, y - 0.15, y + 0.04))
            self.items.append(bar)
            self.text(p["name"], (x + 0.04, y - 0.01), 0.048, rc)
            slot = next((s["name"] for s in SLOTS if s["id"] == p["slot"]), p["slot"])
            self.text(f"{RARITY[p['tier']]} {slot}", (x + 0.04, y - 0.065), 0.034, H.MUTED)
            self.text(part_summary(p), (x + 0.04, y - 0.115), 0.03, H.WHITE)
            can = self.m.cash() >= off["price"]
            self.button(f"${off['price']}", (x + 0.98, y - 0.045), lambda i=i: self.m.act({"a": "buy_part", "i": i}),
                        0.22, 0.08, hot=True, enabled=can)
        owned = sorted(inv.get("parts", {}).items(), key=lambda kv: (parts.get(kv[0], {}).get("slot", ""), kv[0]))
        line = ",  ".join(f"{parts[k]['name']} x{n}" for k, n in owned if k in parts)
        self.text("Your parts:  " + (line or "none"), (-1.19, -0.72), 0.034, H.MUTED, wrap=68)


# ---------------------------------------------------------------------------- workbench
class WorkbenchPanel(Panel):
    title = "WORKBENCH  -  any part fits any gun"
    refresh_on_players = False

    def refresh(self):
        e = getattr(self, "entry", None)
        if e is not None:
            try:
                self.name = e.get()
            except Exception:
                pass
        super().refresh()

    def __init__(self, m):
        self.sel = {}
        self.name = ""
        self.preview_key = None
        self.scene = NodePath("preview")
        from . import geom as G
        G.shader_auto(self.scene)
        from .world import make_lights
        make_lights(self.scene, "#fff2e0", "#6a7080", shadows=False)
        self.holder = self.scene.attachNewNode("holder")
        self.gun = None
        lens = PerspectiveLens()
        lens.setFov(30)
        cam = Camera("pcam", lens)
        self.cam = self.scene.attachNewNode(cam)
        self.cam.setPos(0, -4.2, 0.35)
        self.cam.lookAt(0, 0, 0)
        self.lens = lens
        self.dr = m.app.win.makeDisplayRegion(0, 1, 0, 1)
        self.dr.setSort(30)
        self.dr.setClearColorActive(True)
        self.dr.setClearColor((0.1, 0.11, 0.14, 1))
        self.dr.setClearDepthActive(True)
        self.dr.setCamera(self.cam)
        self.t = 0.0
        super().__init__(m)
        self.autofill()

    def owned(self, slot):
        parts = self.m.parts
        used = {}
        for s, pid in self.sel.items():
            used[pid] = used.get(pid, 0) + 1
        out = []
        for pid, n in self.m.inv.get("parts", {}).items():
            p = parts.get(pid)
            if p and p["slot"] == slot:
                out.append(pid)
        out.sort(key=lambda q: (parts[q]["tier"], parts[q]["name"]))
        return out

    def autofill(self):
        parts = self.m.parts
        for s in SLOTS:
            opts = self.owned(s["id"])
            if opts and s["id"] not in self.sel:
                self.sel[s["id"]] = max(opts, key=lambda q: parts[q]["tier"])
        self.refresh()

    def cycle(self, slot, d, required):
        opts = self.owned(slot)
        if not required:
            opts = [None] + opts
        if not opts:
            return
        cur = self.sel.get(slot)
        i = opts.index(cur) if cur in opts else 0
        nxt = opts[(i + d) % len(opts)]
        if nxt:
            self.sel[slot] = nxt
        else:
            self.sel.pop(slot, None)
        self.refresh()

    def valid_selection(self):
        inv = self.m.inv.get("parts", {})
        need = {}
        for pid in self.sel.values():
            need[pid] = need.get(pid, 0) + 1
        sel = {s: pid for s, pid in self.sel.items() if inv.get(pid, 0) >= need[pid]}
        return sel

    def build(self):
        parts = self.m.parts
        sel = self.valid_selection()
        self.sel = sel
        y = 0.62
        for s in SLOTS:
            pid = sel.get(s["id"])
            p = parts.get(pid)
            self.text(s["name"].upper() + ("" if s["required"] else "  (optional)"), (-1.19, y + 0.03), 0.03, H.MUTED)
            if p:
                n = self.m.inv.get("parts", {}).get(pid, 0)
                self.text(f"{p['name']}  x{n}", (-1.19, y - 0.025), 0.044, hexc(RARITY_COLORS[p["tier"]]))
            else:
                have = bool(self.owned(s["id"]))
                self.text("- none -" if have or not s["required"] else "buy one at the supplier", (-1.19, y - 0.025), 0.04,
                          H.MUTED if not s["required"] else H.BAD)
            self.button("<", (-0.3, y - 0.01), lambda s=s: self.cycle(s["id"], -1, s["required"]), 0.08, 0.07)
            self.button(">", (-0.2, y - 0.01), lambda s=s: self.cycle(s["id"], 1, s["required"]), 0.08, 0.07)
            y -= 0.112
        ok = all(sel.get(s["id"]) for s in SLOTS if s["required"])
        self.text("Gun name", (-1.19, -0.33), 0.032, H.MUTED)
        self.entry = DirectEntry(parent=self.root, initialText=self.name, pos=(-1.19, 0, -0.41), scale=0.042, width=12,
                                 numLines=1, entryFont=self.f, text_fg=H.WHITE, frameColor=(0.12, 0.13, 0.16, 1),
                                 relief=DGG.FLAT, command=lambda t: None)
        self.items.append(self.entry)
        self.button("ASSEMBLE", (-0.38, -0.395), self.assemble, 0.36, 0.09, hot=True, enabled=ok)
        if ok:
            st = compute_stats(sel, parts)
            val = gun_value(sel, parts)
            lines = [f"Damage  {st['damage']:.0f}" + (f" x{st['pellets']}" if st["pellets"] > 1 else ""),
                     f"Fire rate  {st['fireRate']:.1f}/s  {'AUTO' if st['auto'] else 'SEMI'}", f"DPS  {st['dps']:.0f}",
                     f"Range  {st['range']:.0f} m", f"Spread  {st['spread']:.1f}", f"Magazine  {st['magSize']}",
                     f"Reload  {st['reloadTime']:.1f} s", f"Melee  {st['melee']:.0f}", f"Zoom  {st['zoom']:.1f}x",
                     f"Speed  {st['moveSpeed'] * 100:.0f}%"]
            for i, l in enumerate(lines):
                self.text(l, (0.08 + (i % 2) * 0.58, 0.02 - (i // 2) * 0.06), 0.038)
            self.text(f"Parts worth ${val}  -  try selling for ${int(val * 1.3)}", (0.08, -0.31), 0.036, H.GOLD)
        else:
            self.text("Pick a receiver, barrel and magazine to assemble a gun.", (0.08, -0.05), 0.036, H.MUTED, wrap=26)
        # guns owned
        guns = self.m.inv.get("guns", [])
        dis = bool(self.m.inv.get("effects", {}).get("disassemble"))
        self.text("YOUR GUNS" + ("" if dis else "   (upgrade the workbench to scrap guns back into parts)"), (-1.19, -0.52), 0.032, H.MUTED)
        for i, g in enumerate(guns[:6]):
            x = -1.19 + (i % 3) * 0.8
            yy = -0.6 - (i // 3) * 0.12
            held = g["id"] == self.m.inv.get("held")
            self.text(("* " if held else "") + g["name"][:16], (x, yy), 0.036, H.GOLD if held else H.WHITE)
            self.button("Hold", (x + 0.5, yy + 0.012), lambda g=g: self.m.act({"a": "hold", "gid": g["id"]}), 0.13, 0.06, scale=0.034)
            if dis:
                self.button("Scrap", (x + 0.65, yy + 0.012), lambda g=g: self.m.act({"a": "disassemble", "gid": g["id"]}), 0.14, 0.06, scale=0.034)
        key = tuple(sorted(sel.items()))
        if key != self.preview_key:
            self.preview_key = key
            if self.gun:
                self.gun.removeNode()
                self.gun = None
            if sel.get("receiver"):
                g, _ = build_gun(self.holder, sel, parts)
                c, size = bounds_center(g)
                g.setPos(-c[0], -c[1], -c[2])
                self.holder.setScale(1.0 / size)
                self.gun = g

    def assemble(self):
        self.name = self.entry.get().strip()
        self.m.act({"a": "craft", "parts": dict(self.sel), "name": self.name})
        self.app.sounds.play("craft", 0.8)

    def update(self, dt):
        self.t += dt
        self.holder.setH(90 + self.t * 30)
        a = self.app.getAspectRatio()
        x0, x1, y0, y1 = 0.05, 1.2, 0.12, 0.72
        self.dr.setDimensions((x0 + a) / (2 * a), (x1 + a) / (2 * a), (y0 + 1) / 2, (y1 + 1) / 2)
        ar = ((x1 - x0) / (2 * a)) * self.app.win.getXSize() / max(1, ((y1 - y0) / 2) * self.app.win.getYSize())
        self.lens.setFov(30 * max(1.0, ar / 1.6), 30 * max(1.0, ar / 1.6) / ar)

    def destroy(self):
        self.app.win.removeDisplayRegion(self.dr)
        self.scene.removeNode()
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
            self.text(f"Parts worth ${g['value']}", (-0.94, 0.3), 0.036)
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
            self.button(("> " if on else "") + f"{g['name']}   (worth ${g['value']})", (-0.35, y), lambda g=g: self.choose(g), 1.15, 0.07,
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
