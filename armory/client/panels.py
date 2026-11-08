"""Shop UIs: supplier terminal, workbench (with live 3D preview), shelves, rival shelves, upgrade board."""
import math

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
            self.text(("* " if held else "") + g["name"][:13] + f" {g.get('cond', 1) * 100:.0f}%", (x, yy), 0.034, H.GOLD if held else H.WHITE)
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

    def on_server(self, msg):
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
