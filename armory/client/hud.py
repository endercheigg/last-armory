"""2D overlay: cash, clock, prompts, toasts, hotbar, crosshair, health/ammo, killfeed, chat, scoreboard."""
import time

from direct.gui.DirectGui import DGG, DirectEntry, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode, TransparencyAttrib

WHITE = (1, 1, 1, 1)
MUTED = (0.68, 0.7, 0.76, 1)
ACCENT = (1.0, 0.6, 0.2, 1)
GOOD = (0.45, 0.92, 0.5, 1)
BAD = (1.0, 0.4, 0.4, 1)
GOLD = (1.0, 0.83, 0.3, 1)
BLUE = (0.5, 0.78, 1.0, 1)


class Bar:
    def __init__(self, parent, x, y, w, h, color, bg=(0, 0, 0, 0.55)):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.bg = DirectFrame(parent=parent, frameColor=bg, frameSize=(x - 0.006, x + w + 0.006, y - 0.006, y + h + 0.006))
        self.fg = DirectFrame(parent=parent, frameColor=color, frameSize=(x, x + w, y, y + h))
        self.value = 1.0

    def set(self, frac, color=None):
        frac = max(0.0, min(1.0, frac))
        if abs(frac - self.value) > 1e-4:
            self.value = frac
            self.fg["frameSize"] = (self.x, self.x + max(1e-4, self.w * frac), self.y, self.y + self.h)
        if color:
            self.fg["frameColor"] = color

    def show(self, on=True):
        for f in (self.bg, self.fg):
            f.show() if on else f.hide()


class Hud:
    def __init__(self, app):
        self.app = app
        f = app.font
        self.f = f
        b = app
        self.root = b.aspect2d.attachNewNode("hud")
        self.tl = b.a2dTopLeft.attachNewNode("tl")
        self.tr = b.a2dTopRight.attachNewNode("tr")
        self.bl = b.a2dBottomLeft.attachNewNode("bl")
        self.br = b.a2dBottomRight.attachNewNode("br")
        self.tc = b.a2dTopCenter.attachNewNode("tc")
        self.bc = b.a2dBottomCenter.attachNewNode("bc")
        self.anchors = [self.root, self.tl, self.tr, self.bl, self.br, self.tc, self.bc]

        def T(parent, pos, scale, fg=WHITE, align=TextNode.ACenter):
            return OnscreenText(text="", parent=parent, pos=pos, scale=scale, fg=fg, align=align, font=f,
                                shadow=(0, 0, 0, 0.85), mayChange=True)
        self.T = T
        self.vignette = DirectFrame(parent=self.root, frameColor=(0.8, 0, 0, 0), frameSize=(-3, 3, -1, 1))
        self.vignette.setTransparency(TransparencyAttrib.MAlpha)
        self.title = T(self.tc, (0, -0.085), 0.065)
        self.sub = T(self.tc, (0, -0.145), 0.04, MUTED)
        self.big = T(self.root, (0, 0.3), 0.15)
        self.big_sub = T(self.root, (0, 0.19), 0.05, MUTED)
        self.big_until = 0.0
        self.server = T(self.tl, (0.04, -0.07), 0.038, MUTED, TextNode.ALeft)
        self.cash = T(self.tr, (-0.05, -0.1), 0.085, GOLD, TextNode.ARight)
        self.cash_shown = None
        self.money_pops = []
        self.prompt = T(self.root, (0, -0.2), 0.05, WHITE)
        self.toast = T(self.root, (0, -0.32), 0.05, BAD)
        self.toast_until = 0.0
        self.hint = T(self.bc, (0, 0.04), 0.034, MUTED)
        self.hotbar = [T(self.bc, (-0.75 + i * 0.3, 0.12), 0.036, MUTED) for i in range(6)]
        self.hotbar_bg = [DirectFrame(parent=self.bc, frameColor=(0, 0, 0, 0.45), frameSize=(-0.14, 0.14, -0.025, 0.06),
                                      pos=(-0.75 + i * 0.3, 0, 0.12)) for i in range(6)]
        for bg in self.hotbar_bg:
            bg.setBin("fixed", 0)
        self.armor_bar = Bar(self.bl, 0.07, 0.15, 0.51, 0.02, BLUE)
        self.armor_text = T(self.bl, (0.6, 0.147), 0.032, BLUE, TextNode.ALeft)
        self.hunger_bar = Bar(self.bl, 0.07, 0.27, 0.24, 0.016, (0.95, 0.65, 0.25, 1))
        self.energy_bar = Bar(self.bl, 0.34, 0.27, 0.24, 0.016, (0.55, 0.8, 1.0, 1))
        self.hunger_text = T(self.bl, (0.07, 0.295), 0.028, MUTED, TextNode.ALeft)
        self.energy_text = T(self.bl, (0.34, 0.295), 0.028, MUTED, TextNode.ALeft)
        self.zone = T(self.tl, (0.04, -0.13), 0.045, GOOD, TextNode.ALeft)
        # "NEXT" guide box
        self.guide_bg = DirectFrame(parent=self.tl, frameColor=(0, 0, 0, 0.42), frameSize=(0.025, 0.93, -0.47, -0.17))
        self.guide_head = T(self.tl, (0.045, -0.215), 0.036, GOLD, TextNode.ALeft)
        self.guide_text = OnscreenText(text="", parent=self.tl, pos=(0.045, -0.262), scale=0.035, fg=WHITE, align=TextNode.ALeft,
                                       font=f, shadow=(0, 0, 0, 0.85), mayChange=True, wordwrap=24.5)
        self.guide_shown = None
        self.guide_bg.hide()
        # sprint stamina (only visible while it is not full)
        self.stamina_bar = Bar(self.root, -0.13, -0.47, 0.26, 0.012, (0.95, 0.9, 0.45, 1))
        self.stamina_bar.show(False)
        self.stamina_on = False
        # waypoint markers
        self.markers = [T(self.root, (0, 0), 0.034, GOLD) for _ in range(6)]
        self.marker_dots = [DirectFrame(parent=self.root, frameColor=(1, 1, 1, 0), frameSize=(-0.011, 0.011, -0.011, 0.011))
                            for _ in range(6)]
        for d in self.marker_dots:
            d.setR(45)
        self.sleep_fade = DirectFrame(parent=self.root, frameColor=(0, 0, 0.02, 0), frameSize=(-3, 3, -1, 1))
        self.sleep_fade.setTransparency(TransparencyAttrib.MAlpha)
        self.sleep_text = T(self.root, (0, 0), 0.07, (0.8, 0.85, 1, 1))
        self.hp_label = T(self.bl, (0.07, 0.205), 0.04, MUTED, TextNode.ALeft)
        self.hp_text = T(self.bl, (0.58, 0.195), 0.06, WHITE, TextNode.ARight)
        self.hp_bar = Bar(self.bl, 0.07, 0.09, 0.51, 0.045, GOOD)
        self.ammo = T(self.br, (-0.08, 0.09), 0.1, WHITE, TextNode.ARight)
        self.ammo_sub = T(self.br, (-0.08, 0.2), 0.04, MUTED, TextNode.ARight)
        self.reload_bar = Bar(self.br, -0.5, 0.06, 0.42, 0.015, ACCENT)
        self.reload_bar.show(False)
        self.alive = T(self.tr, (-0.05, -0.18), 0.045, WHITE, TextNode.ARight)
        self.cross = [DirectFrame(parent=self.root, frameColor=(1, 1, 1, 0.9), frameSize=(0, 0, 0, 0)) for _ in range(5)]
        self.hitmark = [DirectFrame(parent=self.root, frameColor=(1, 1, 1, 0), frameSize=(-0.004, 0.004, 0.012, 0.03)) for _ in range(4)]
        for i, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
            self.hitmark[i].setR(45 if sx * sy > 0 else -45)
            self.hitmark[i].setPos(sx * 0.02, 0, sy * 0.02)
        self.hit_t = 0.0
        self.hit_head = False
        self.spec = T(self.bc, (0, 0.28), 0.05)
        self.killfeed = []
        self.kill_texts = [T(self.tr, (-0.05, -0.26 - i * 0.05), 0.037, WHITE, TextNode.ARight) for i in range(5)]
        self.chat = []
        self.chat_texts = [T(self.bl, (0.05, 0.45 + i * 0.048), 0.036, WHITE, TextNode.ALeft) for i in range(8)]
        self.chat_entry = None
        self.board = DirectFrame(parent=self.root, frameColor=(0.05, 0.06, 0.08, 0.9), frameSize=(-0.85, 0.85, -0.66, 0.62), pos=(0, 0, -0.1))
        self.board_title = T(self.board, (0, 0.5), 0.075, ACCENT)
        self.board_lines = [T(self.board, (-0.78, 0.38 - i * 0.066), 0.044, WHITE, TextNode.ALeft) for i in range(15)]
        self.board_cols = [T(self.board, (0.78, 0.38 - i * 0.066), 0.044, WHITE, TextNode.ARight) for i in range(15)]
        self.board.hide()

    # ------------------------------------------------------------------ helpers
    def flash_big(self, text, sub="", color=WHITE, dur=1.6, y=0.3):
        self.big.setPos(0, y)
        self.big_sub.setPos(0, y - 0.11)
        self.big.setText(text)
        self.big.setFg(color)
        self.big_sub.setText(sub)
        self.big_until = time.monotonic() + dur

    def show_toast(self, text, bad=True, dur=2.2):
        self.toast.setText(text)
        self.toast.setFg(BAD if bad else GOOD)
        self.toast_until = time.monotonic() + dur

    def money(self, n, why):
        col = GOOD if n >= 0 else BAD
        t = self.T(self.tr, (-0.05, -0.2), 0.042, col, TextNode.ARight)
        t.setText(f"{'+' if n >= 0 else '-'}${abs(n)}   {why}")
        self.money_pops.append([t, time.monotonic(), col])
        if len(self.money_pops) > 5:
            self.money_pops.pop(0)[0].destroy()

    def set_cash(self, n):
        if n != self.cash_shown:
            self.cash_shown = n
            self.cash.setText(f"${n:,}")

    def set_hotbar(self, guns, held):
        for i, (t, bg) in enumerate(zip(self.hotbar, self.hotbar_bg)):
            if i < len(guns):
                g = guns[i]
                t.setText(f"{i + 1}  {g['name'][:14]}")
                on = g["id"] == held
                t.setFg(GOLD if on else WHITE)
                bg["frameColor"] = (0.35, 0.22, 0.05, 0.75) if on else (0, 0, 0, 0.45)
                bg.show()
            else:
                t.setText("")
                bg.hide()

    def set_vitals(self, hp, armor, hunger, energy, sleeping):
        frac = hp / 100.0
        self.hp_label.setText("HEALTH")
        self.hp_text.setText(str(int(hp)))
        self.hp_bar.set(frac, GOOD if frac > 0.5 else (1, 0.8, 0.3, 1) if frac > 0.25 else BAD)
        self.armor_bar.set(armor / 50.0)
        self.armor_text.setText(f"{int(armor)}" if armor > 0 else "")
        self.hunger_bar.set(hunger / 100.0, (0.95, 0.65, 0.25, 1) if hunger > 20 else BAD)
        self.energy_bar.set(energy / 100.0, (0.55, 0.8, 1.0, 1) if energy > 25 else BAD)
        self.hunger_text.setText("FOOD" + ("  - starving!" if hunger <= 0 else "  - hungry" if hunger < 20 else ""))
        self.energy_text.setText("ENERGY" + ("  - exhausted!" if energy <= 0 else "  - tired" if energy < 25 else ""))
        c = self.sleep_fade["frameColor"]
        target = 0.82 if sleeping else 0.0
        self.sleep_fade["frameColor"] = (0, 0, 0.02, c[3] + (target - c[3]) * 0.08)
        self.sleep_text.setText(f"Sleeping...  energy {int(energy)}%" + chr(10) + "(press E to wake up)" if sleeping else "")

    def set_guide(self, head, body):
        if (head, body) == self.guide_shown:
            return
        self.guide_shown = (head, body)
        self.guide_head.setText(head)
        self.guide_text.setText(body)
        if body:
            lines = max(1, len(body) // 44 + 1)
            self.guide_bg["frameSize"] = (0.025, 0.93, -0.275 - lines * 0.04, -0.17)
            self.guide_bg.show()
        else:
            self.guide_bg.hide()

    def set_stamina(self, st):
        on = st < 99.5
        if on != self.stamina_on:
            self.stamina_on = on
            self.stamina_bar.show(on)
        if on:
            self.stamina_bar.set(st / 100.0, (0.95, 0.9, 0.45, 1) if st > 25 else BAD)

    def set_markers(self, items):
        for i, (t, d) in enumerate(zip(self.markers, self.marker_dots)):
            if i < len(items):
                x, y, label, color = items[i]
                t.setText(label)
                t.setFg(color)
                t.setPos(x, y + 0.03)
                d["frameColor"] = (color[0], color[1], color[2], 0.9)
                d.setPos(x, 0, y)
            else:
                t.setText("")
                d["frameColor"] = (1, 1, 1, 0)

    def show_combat(self, on):
        for w in (self.hp_label, self.hp_text, self.ammo, self.ammo_sub):
            w.show() if on else w.hide()
        self.hp_bar.show(on)
        if not on:
            self.reload_bar.show(False)

    def hurt(self, amount):
        self.vignette["frameColor"] = (0.8, 0, 0, min(0.28, 0.08 + amount / 200))

    def hit(self, head):
        self.hit_t = 0.18
        self.hit_head = head

    def add_kill(self, text, mine):
        self.killfeed.append((time.monotonic(), text, ACCENT if mine else WHITE))
        self.killfeed = self.killfeed[-5:]

    def add_chat(self, who, msg, color):
        self.chat.append((time.monotonic(), f"{who}: {msg}" if who else msg, color))
        self.chat = self.chat[-40:]

    def set_crosshair(self, gap):
        if gap is None:
            for c in self.cross:
                c["frameSize"] = (0, 0, 0, 0)
            return
        g = max(0.01, min(0.25, gap))
        L, W = 0.022, 0.0026
        sizes = [(g, g + L, -W, W), (-g - L, -g, -W, W), (-W, W, g, g + L), (-W, W, -g - L, -g), (-W, W, -W, W)]
        for c, fs in zip(self.cross, sizes):
            c["frameSize"] = fs

    def show_board(self, title, rows):
        self.board.show()
        self.board_title.setText(title)
        for i in range(len(self.board_lines)):
            if i < len(rows):
                name, right, color = rows[i]
                self.board_lines[i].setText(name)
                self.board_lines[i].setFg(color)
                self.board_cols[i].setText(right)
                self.board_cols[i].setFg(color)
            else:
                self.board_lines[i].setText("")
                self.board_cols[i].setText("")

    def hide_board(self):
        self.board.hide()

    def open_chat(self, on_send):
        if self.chat_entry:
            return

        def done(text):
            self.close_chat()
            on_send(text)
        self.chat_entry = DirectEntry(parent=self.bl, pos=(0.05, 0, 0.38), scale=0.04, width=28, numLines=1, focus=1,
                                      command=done, frameColor=(0, 0, 0, 0.7), text_fg=WHITE, entryFont=self.f, relief=DGG.FLAT)

    def close_chat(self):
        if self.chat_entry:
            self.chat_entry.destroy()
            self.chat_entry = None

    # ------------------------------------------------------------------ frame
    def update(self, dt, chat_open=False):
        now = time.monotonic()
        if self.big_until and now > self.big_until:
            self.big.setText("")
            self.big_sub.setText("")
            self.big_until = 0
        if self.toast_until and now > self.toast_until:
            self.toast.setText("")
            self.toast_until = 0
        c = self.vignette["frameColor"]
        if c[3] > 0:
            self.vignette["frameColor"] = (c[0], c[1], c[2], max(0, c[3] - dt * 1.4))
        self.hit_t = max(0, self.hit_t - dt)
        a = min(1, self.hit_t / 0.1)
        col = (1, 0.3, 0.3, a) if self.hit_head else (1, 1, 1, a)
        for h in self.hitmark:
            h["frameColor"] = col
        keep = []
        for idx, (t, born, col) in enumerate(reversed(self.money_pops)):
            age = now - born
            if age > 3.5:
                t.destroy()
                continue
            t.setPos(-0.05, -0.2 - idx * 0.05)
            t.setFg((col[0], col[1], col[2], max(0, 1 - max(0, age - 2.8) / 0.7)))
            keep.append([t, born, col])
        self.money_pops = list(reversed(keep))
        lines = [k for k in self.killfeed if now - k[0] < 7]
        for i, t in enumerate(self.kill_texts):
            if i < len(lines):
                t.setText(lines[-1 - i][1])
                t.setFg(lines[-1 - i][2])
            else:
                t.setText("")
        chat = [c for c in self.chat if chat_open or now - c[0] < 10][-len(self.chat_texts):]
        for i, t in enumerate(self.chat_texts):
            j = len(chat) - 1 - i
            if j >= 0:
                t.setText(chat[j][1])
                t.setFg(chat[j][2])
            else:
                t.setText("")

    def destroy(self):
        self.close_chat()
        for t, _, _ in self.money_pops:
            t.destroy()
        for a in self.anchors:
            a.removeNode()
