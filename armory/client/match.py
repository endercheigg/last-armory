"""In-match controller: network messages, phases, panels, input glue, HUD."""
import time

from direct.gui.DirectGui import DGG, DirectButton, DirectFrame, DirectSlider
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode, WindowProperties

from ..gun import compute_stats
from ..town import build_town
from . import hud as H
from .geom import hexc
from .world import LobbyView, NightView, TownView, key_down


class Match:
    def __init__(self, app, conn, welcome, on_leave):
        self.app = app
        self.conn = conn
        self.on_leave = on_leave
        self.me = welcome["id"]
        self.server = welcome["server"]
        self.apply_welcome(welcome)
        self.world_root = None
        self.world = app.render.attachNewNode("match")
        self.hud = H.Hud(app)
        self.hud.server.setText(self.server["name"])
        self.infos = {}
        self.inv = {"parts": {}, "guns": [], "stock": [], "held": None, "effects": {}}
        self.stats_cache = {}
        self.view = None
        self.phase = None
        self.day = 0
        self.phase_left = 0
        self.alive_count = 0
        self.menu = None
        self.menu_open = False
        self.chat_open = False
        self.panel = None
        self.captured = False
        self.closed = False
        self.pending_tp = None
        app.accept("escape", self.on_escape)
        app.accept("enter", self.open_chat)
        app.accept("t", self.open_chat)
        app.accept("e", self.on_use)
        for i in range(6):
            app.accept(str(i + 1), self.hold_index, [i])
        self.handle(welcome["phase"])

    def apply_welcome(self, w):
        self.content = w["content"]
        self.parts = self.content["parts"]
        content = {"towns": w["towns"], "shops": w["shops"]}
        self.town = build_town(content, w.get("town"), w.get("shop"))
        self.stats_cache = {}

    # ---------------------------------------------------------------- data helpers
    def cash(self):
        return self.infos.get(self.me, {}).get("cash", 0)

    def stats(self, pid):
        info = self.infos.get(pid)
        if not info or not info.get("held"):
            return None
        key = tuple(sorted(info["held"].items()))
        s = self.stats_cache.get(key)
        if s is None:
            s = compute_stats(info["held"], self.parts)
            self.stats_cache[key] = s
        return s

    def name(self, pid):
        return self.infos.get(pid, {}).get("name", "?")

    def act(self, msg):
        self.conn.send(dict(msg, t="act"))

    # ---------------------------------------------------------------- input glue
    def set_capture(self, on):
        if on == self.captured:
            return
        self.captured = on
        self.last_ptr = None
        if not hasattr(self.app.win, "requestProperties"):
            return
        wp = WindowProperties()
        wp.setCursorHidden(on)
        wp.setMouseMode(self.app.capture_mode if on else WindowProperties.M_absolute)
        self.app.win.requestProperties(wp)
        if on:
            self.recenter()

    def recenter(self):
        w = self.app.win
        if hasattr(w, "movePointer"):
            return w.movePointer(0, w.getXSize() // 2, w.getYSize() // 2)
        return False

    def mouse_delta(self):
        """Works with warp-to-center (Windows/Linux) and with relative mode (macOS)."""
        w = self.app.win
        if not hasattr(w, "getPointer"):
            return 0, 0
        md = w.getPointer(0)
        x, y = md.getX(), md.getY()
        last = getattr(self, "last_ptr", None)
        dx, dy = (0, 0) if last is None else (x - last[0], y - last[1])
        if self.recenter():
            self.last_ptr = (w.getXSize() // 2, w.getYSize() // 2)
        else:
            self.last_ptr = (x, y)
        if abs(dx) > w.getXSize() // 3 or abs(dy) > w.getYSize() // 3:
            return 0, 0
        return dx, dy

    def hold_index(self, i):
        if (self.panel and self.panel.typing) or self.chat_open or self.menu_open:
            return
        guns = self.inv.get("guns", [])
        if i < len(guns):
            self.act({"a": "hold", "gid": guns[i]["id"]})

    def on_use(self):
        if self.chat_open or self.menu_open:
            return
        if self.panel:
            if not self.panel.typing:
                self.close_panel()
            return
        if isinstance(self.view, TownView):
            self.view.interact()

    def open_panel(self, panel):
        self.close_panel()
        self.panel = panel
        self.set_capture(False)

    def close_panel(self):
        if self.panel:
            self.panel.destroy()
            self.panel = None

    def open_chat(self):
        if self.chat_open or self.menu_open or self.panel:
            return
        self.chat_open = True
        self.set_capture(False)

        def send(text):
            self.chat_open = False
            if text.strip():
                self.conn.send({"t": "chat", "msg": text})
        self.hud.open_chat(send)

    def on_escape(self):
        if self.chat_open:
            self.hud.close_chat()
            self.chat_open = False
        elif self.panel:
            self.close_panel()
        elif self.menu_open:
            self.close_menu()
        else:
            self.open_menu()

    def open_menu(self):
        self.menu_open = True
        self.set_capture(False)
        app = self.app
        f = app.font
        fr = DirectFrame(parent=app.aspect2d, frameColor=(0.04, 0.05, 0.07, 0.93), frameSize=(-0.6, 0.6, -0.62, 0.62))
        OnscreenText(parent=fr, text="PAUSED", pos=(0, 0.48), scale=0.09, fg=H.ACCENT, font=f)
        OnscreenText(parent=fr, text="(the game keeps going)", pos=(0, 0.41), scale=0.04, fg=H.MUTED, font=f)

        def btn(label, y, cmd):
            DirectButton(parent=fr, text=label, pos=(0, 0, y), scale=0.065, command=cmd, text_font=f, text_fg=H.WHITE,
                         frameColor=((0.2, 0.22, 0.26, 1), (0.3, 0.33, 0.38, 1), (0.3, 0.33, 0.38, 1), (0.1, 0.1, 0.1, 1)),
                         relief=DGG.FLAT, frameSize=(-3.6, 3.6, -0.6, 1.0), pressEffect=0)
        btn("Resume", 0.26, self.close_menu)
        btn("Leave game", 0.12, lambda: self.leave(None))

        def slider(label, y, lo, hi, key, fmt):
            t = OnscreenText(parent=fr, text="", pos=(-0.5, y - 0.015), scale=0.042, fg=H.WHITE, align=TextNode.ALeft, font=f, mayChange=True)

            def changed():
                v = s["value"]
                app.settings[key] = v
                t.setText(f"{label}: {fmt(v)}")
                if key == "volume":
                    app.sounds.volume = v
            s = DirectSlider(parent=fr, range=(lo, hi), value=app.settings[key], pos=(0.22, 0, y), scale=0.3, command=changed,
                             frameColor=(0.2, 0.22, 0.26, 1), thumb_frameColor=H.ACCENT)
            changed()
        slider("Mouse", -0.06, 0.02, 0.5, "sens", lambda v: f"{v:.2f}")
        slider("FOV", -0.18, 60, 110, "fov", lambda v: f"{v:.0f}")
        slider("Volume", -0.3, 0, 1, "volume", lambda v: f"{v * 100:.0f}%")
        OnscreenText(parent=fr, text="Mods: " + ", ".join(m["name"] for m in self.content.get("mods", [])), pos=(0, -0.48),
                     scale=0.035, fg=H.MUTED, font=f, wordwrap=30)
        self.menu = fr

    def close_menu(self):
        if self.menu:
            self.menu.destroy()
            self.menu = None
        self.menu_open = False
        self.app.save_settings()

    def leave(self, reason):
        if not self.closed:
            self.closed = True
            self.on_leave(reason)

    # ---------------------------------------------------------------- network
    def handle(self, m):
        t = m.get("t")
        v = self.view
        if t == "s":
            self.phase_left = m.get("left", 0)
            if v and hasattr(v, "on_snapshot") and m.get("ph") == self.phase:
                v.on_snapshot(m)
        elif t == "players":
            self.infos = {p["id"]: p for p in m["list"]}
            if self.panel and self.panel.refresh_on_players:
                self.panel.refresh()
        elif t == "inv":
            self.inv = m
            if self.panel:
                self.panel.refresh()
        elif t == "phase":
            self.set_phase(m)
        elif t == "cash":
            if m["p"] == self.me:
                self.hud.money(m["n"], m["why"])
                if m["n"] > 0:
                    self.app.sounds.play("cash", 0.7)
        elif t == "sale":
            if m["seller"] == self.me:
                self.hud.show_toast(f"{m['buyer']} bought your {m['gun']} for ${m['price']}!", bad=False, dur=3)
        elif t == "crafted" and m["p"] == self.me:
            self.hud.show_toast(f"Assembled: {m['gun']['name']}  (worth ${m['gun']['value']})", bad=False)
        elif t == "toast":
            self.hud.show_toast(m["msg"], bool(m.get("bad", 1)))
            self.app.sounds.play("gate_bad", 0.4)
        elif t == "cust" and isinstance(v, TownView):
            v.on_customer(m)
        elif t == "cb" and isinstance(v, TownView):
            v.on_cbubble(m)
        elif t == "thit" and isinstance(v, TownView):
            v.on_target_hit(m)
            if m["p"] == self.me:
                self.app.sounds.play("hit", 0.5)
        elif t == "shot" and v and hasattr(v, "on_shot"):
            v.on_shot(m)
        elif t == "melee" and v and hasattr(v, "on_melee"):
            v.on_melee(m)
        elif t == "boom" and v and hasattr(v, "on_boom"):
            v.on_boom(m)
        elif t == "zdead" and isinstance(v, NightView):
            v.on_zdead(m)
        elif t == "dmg":
            if v and hasattr(v, "on_damage"):
                v.on_damage(m)
            if m["a"] == self.me and m["v"] != self.me:
                self.hud.hit(bool(m.get("hd")))
                self.app.sounds.play("headshot" if m.get("hd") else "hit", 0.6)
            if m["v"] == self.me:
                self.hud.hurt(m["n"])
                self.app.sounds.play("hurt", 0.6)
        elif t == "kill":
            k, vv = m["k"], m["v"]
            txt = f"{self.name(k)}  [{m.get('gun', '')}]  {self.name(vv)}" if k else f"{self.name(vv)} was eaten by zombies"
            self.hud.add_kill(txt, self.me in (k, vv))
            if k == self.me and vv != self.me:
                self.app.sounds.play("kill", 0.8)
                self.hud.flash_big("ELIMINATED", self.name(vv), H.ACCENT, 1.4)
            if vv == self.me:
                self.hud.flash_big("YOU'RE DOWN", f"by {self.name(k)}" if k else "the zombies got you", H.BAD, 2.5)
        elif t == "chat":
            self.hud.add_chat(m.get("from", ""), m.get("msg", ""), hexc(m.get("color", "#ffffff")))
        elif t == "tp":
            if v and hasattr(v, "teleport"):
                v.teleport(m)
            else:
                self.pending_tp = m
        elif t == "welcome":
            self.apply_welcome(m)
        elif t == "kicked":
            self.leave(m.get("reason", "Kicked"))

    def set_phase(self, m):
        ph = m["phase"]
        prev = self.phase
        self.phase = ph
        self.day = m.get("day", self.day)
        self.hud.hide_board()
        if ph in ("lobby",):
            self.close_panel()
            self.swap(LobbyView(self))
        elif ph == "day":
            self.swap(None)
            self.swap(TownView(self, self.town))
            self.hud.flash_big(f"DAY {self.day}", "Build guns. Fill your shelves. Sell!", H.GOLD, 3)
            self.app.sounds.play("go", 0.6)
        elif ph == "night":
            self.close_panel()
            self.swap(None)
            self.swap(NightView(self, m))
        elif ph == "dawn":
            self.hud.flash_big("DAWN", "The shops open soon...", H.GOLD, 3.5)
        elif ph == "results":
            w = m.get("winner")
            self.hud.flash_big(f"{self.name(w).upper()} WINS!" if w else "GAME OVER", "Richest gunsmith in town", H.GOLD, 14, y=0.62)
            self.app.sounds.play("win", 0.8)
        if self.pending_tp and self.view and hasattr(self.view, "teleport"):
            self.view.teleport(self.pending_tp)
            self.pending_tp = None

    def swap(self, view):
        if self.view:
            self.view.destroy()
        self.view = view

    def show_scores(self, title):
        rows = []
        for p in sorted(self.infos.values(), key=lambda p: -p["cash"]):
            col = H.ACCENT if p["id"] == self.me else H.WHITE
            rows.append((p["name"], f"${p['cash']:,}    {p['kills']} kills   {p['zkills']} zombies", col))
        self.hud.show_board(title, rows)

    # ---------------------------------------------------------------- frame
    def update(self, dt):
        for msg in self.conn.poll():
            self.handle(msg)
            if self.closed:
                return
        if self.conn.closed:
            self.leave("Lost connection to the server" + (f"\n{self.conn.error}" if self.conn.error else ""))
            return
        if self.view:
            self.view.update(dt)
        if not hasattr(self.view, "controls_enabled"):
            self.set_capture(False)
        if self.panel:
            self.panel.update(dt)
        ph = self.phase
        mins, secs = divmod(int(self.phase_left), 60)
        days = self.server.get("days", 5)
        if ph == "lobby":
            self.hud.title.setText("LOBBY")
            self.hud.sub.setText(f"Starting in {self.phase_left:.0f}s  -  {len(self.infos)} gunsmiths" if self.phase_left > 0 else "Waiting for players...")
        elif ph == "day":
            self.hud.title.setText(f"DAY {self.day} / {days}")
            self.hud.sub.setText(f"Night falls in {mins}:{secs:02d}")
        elif ph == "night":
            self.hud.title.setText(f"NIGHT {self.day}")
            self.hud.sub.setText(f"{mins}:{secs:02d}  -  last one standing takes the bounty")
        elif ph == "dawn":
            self.hud.sub.setText("")
        elif ph == "results":
            self.hud.title.setText("FINAL RESULTS")
            self.hud.sub.setText("")
        self.hud.set_cash(self.cash())
        self.hud.set_hotbar(self.inv.get("guns", []), self.inv.get("held"))
        tab = key_down(self.app, "tab") and not self.chat_open
        if ph == "results":
            self.show_scores("FINAL RESULTS")
        elif tab:
            self.show_scores("RICHEST GUNSMITHS")
        else:
            self.hud.hide_board()
        self.hud.update(dt, self.chat_open)

    def destroy(self):
        self.set_capture(False)
        for k in ["escape", "enter", "t", "e"] + [str(i + 1) for i in range(6)]:
            self.app.ignore(k)
        self.close_panel()
        self.close_menu()
        if self.view:
            self.view.destroy()
        self.hud.destroy()
        self.world.removeNode()
        try:
            self.conn.close()
        except Exception:
            pass
