"""Window, menus, hosting and joining (Windows, macOS, Linux)."""
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time

from panda3d.core import loadPrcFileData

from .. import DEFAULT_PORT, PROTOCOL, VERSION

DEFAULT_SETTINGS = {"name": "", "sens": 0.12, "fov": 85.0, "volume": 0.7, "fullscreen": False, "graphics": "high",
                    "last_address": "127.0.0.1", "recent": [], "host_port": DEFAULT_PORT, "host_min": 4,
                    "host_bots": True, "host_first": 5, "host_name": ""}

FONT_CANDIDATES = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                   "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def user_data_dir(root):
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/LastArmory")
    if sys.platform.startswith("linux"):
        return os.path.expanduser("~/.local/share/LastArmory")
    return os.path.join(root, "userdata")


def configure(extra=""):
    if getattr(sys, "frozen", False):
        # packaged build: point Panda3D at its bundled plugins (renderer, audio)
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        pdir = os.path.join(base, "panda3d")
        loadPrcFileData("", "plugin-path " + pdir.replace("\\", "/"))
        loadPrcFileData("", "load-display pandagl")
        loadPrcFileData("", "audio-library-name p3openal_audio")
        os.environ["PATH"] = pdir + os.pathsep + os.environ.get("PATH", "")
    loadPrcFileData("", f"""
window-title LAST ARMORY
win-size 1280 720
framebuffer-multisample 1
multisamples 4
sync-video 1
textures-power-2 none
show-frame-rate-meter 0
{extra}
""")


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def parse_address(a):
    a = a.strip()
    if not a:
        return None, None
    if a.count(":") == 1:
        h, p = a.split(":")
        try:
            return h.strip(), int(p)
        except ValueError:
            return None, None
    return a, DEFAULT_PORT


def run(root, extra_prc=""):
    configure(extra_prc)
    from direct.showbase.ShowBase import ShowBase  # noqa: import after prc config
    from direct.gui.DirectGui import DGG, DirectButton, DirectCheckButton, DirectEntry, DirectFrame, DirectSlider
    from direct.gui.OnscreenText import OnscreenText
    from panda3d.core import Filename, TextNode, WindowProperties, AntialiasAttrib

    from ..content import load_content
    from . import hud as H
    from .geom import build_gun, bounds_center, box, hexc
    from .match import Match
    from .world import make_lights
    from .net import Connection
    from .sound import Sounds

    class App(ShowBase):
        def __init__(self):
            ShowBase.__init__(self)
            self.root_dir = root
            self.data_dir = user_data_dir(root)
            self.capture_mode = WindowProperties.M_relative if sys.platform == "darwin" else WindowProperties.M_confined
            os.makedirs(self.data_dir, exist_ok=True)
            self.settings = dict(DEFAULT_SETTINGS)
            try:
                with open(os.path.join(self.data_dir, "settings.json"), encoding="utf-8") as f:
                    self.settings.update(json.load(f))
            except (OSError, json.JSONDecodeError):
                pass
            if not self.settings["name"]:
                self.settings["name"] = f"Gunsmith{int(time.time()) % 1000}"
            self.disableMouse()
            from . import geom as G
            G.FANCY = self.settings.get("graphics", "high") != "compat" and "--compat" not in sys.argv
            G.shader_auto(self.render)
            self.render.setAntialias(AntialiasAttrib.MMultisample)
            self.camLens.setFov(self.settings["fov"])
            self.font = self.font3d = None
            for path in FONT_CANDIDATES:
                if os.path.isfile(path):
                    f = self.loader.loadFont(Filename.fromOsSpecific(path).getFullpath())
                    if f and f.isValid():
                        f.setPixelsPerUnit(72)
                        self.font = self.font3d = f
                        break
            if self.font is None:
                self.font = self.font3d = self.loader.loadFont("cmss12")
            self.sounds = Sounds(self, os.path.join(self.data_dir, "sfx"))
            self.sounds.volume = self.settings["volume"]
            self.local = load_content(os.path.join(root, "mods"), load_scripts=False)
            self.server_proc = None
            self.match = None
            self.menu = None
            self.showcase = None
            self.connecting = None
            self.accept("f11", self.toggle_fullscreen)
            self.accept("window-event", self.on_window)
            if self.settings["fullscreen"]:
                self.apply_fullscreen(True)
            self.taskMgr.add(self.tick, "tick")
            self.main_menu()

        # ------------------------------------------------------------ misc
        def save_settings(self):
            try:
                with open(os.path.join(self.data_dir, "settings.json"), "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
            except OSError:
                pass

        def on_window(self, win):
            if win is self.win and not self.win.getProperties().getOpen():
                self.quit()

        def toggle_fullscreen(self):
            self.settings["fullscreen"] = not self.settings["fullscreen"]
            self.apply_fullscreen(self.settings["fullscreen"])
            self.save_settings()

        def apply_fullscreen(self, on):
            wp = WindowProperties()
            if on:
                wp.setFullscreen(True)
                wp.setSize(self.pipe.getDisplayWidth(), self.pipe.getDisplayHeight())
            else:
                wp.setFullscreen(False)
                wp.setSize(1280, 720)
            self.win.requestProperties(wp)

        def quit(self):
            if self.match:
                self.match.destroy()
            self.stop_server()
            self.save_settings()
            sys.exit(0)

        # ------------------------------------------------------------ showcase
        def start_showcase(self):
            if self.showcase:
                return
            node = self.render.attachNewNode("showcase")
            self.setBackgroundColor(*hexc("#12151c"))
            make_lights(node, "#fff2e0", "#6a7080", film=6)
            box(node, (0, 0, -0.62), (3, 3, 0.1), hexc("#232833"))
            self.showcase = {"node": node, "gun": None, "t": 0.0, "i": -1, "next": 0.0}
            self.camera.setPos(0.75, -2.2, 0.45)
            self.camera.lookAt(0.6, 0, -0.02)

        def showcase_tick(self, dt):
            s = self.showcase
            if not s:
                return
            s["t"] += dt
            if s["t"] >= s["next"]:
                s["next"] = s["t"] + 2.4
                s["i"] += 1
                parts = self.local["parts"]
                tiers = sorted({p["tier"] for p in parts.values()})
                tier = tiers[s["i"] % len(tiers)] if tiers else 0
                lo = {}
                for slot in ("receiver", "barrel", "magazine", "stock", "sight", "muzzle"):
                    opts = [p for p in parts.values() if p["slot"] == slot and p["tier"] <= tier]
                    best = [p for p in opts if p["tier"] == max((o["tier"] for o in opts), default=0)]
                    if best:
                        lo[slot] = best[(s["i"] * 7 + len(slot)) % len(best)]["id"]
                if s["gun"]:
                    s["gun"].removeNode()
                holder = s["node"].attachNewNode("holder")
                g, _ = build_gun(holder, lo, parts)
                c, size = bounds_center(g)
                g.setPos(-c[0], -c[1], -c[2])
                s["base"] = 1.05 / size
                holder.setScale(s["base"] * 0.05)
                holder.setPos(0.62, 0, 0.02)
                s["gun"] = holder
                s["pop"] = 0.0
            if s["gun"]:
                s["pop"] = min(1.0, s["pop"] + dt * 4)
                k = 1 - (1 - s["pop"]) ** 3
                s["gun"].setH(90 + math.sin(s["t"] * 0.7) * 40)
                s["gun"].setZ(math.sin(s["t"] * 1.3) * 0.03)
                s["gun"].setScale(s["base"] * max(0.05, k))

        def stop_showcase(self):
            if self.showcase:
                self.showcase["node"].removeNode()
                self.showcase = None

        # ------------------------------------------------------------ menu widgets
        def clear_menu(self):
            if self.menu:
                self.menu.destroy()
                self.menu = None

        def frame(self):
            self.clear_menu()
            self.start_showcase()
            self.menu = DirectFrame(parent=self.a2dLeftCenter, frameColor=(0, 0, 0, 0))
            return self.menu

        def label(self, parent, s, pos, scale=0.05, fg=H.WHITE, align=TextNode.ALeft):
            return OnscreenText(parent=parent, text=s, pos=pos, scale=scale, fg=fg, align=align, font=self.font,
                                shadow=(0, 0, 0, 0.6), mayChange=True)

        def button(self, parent, s, pos, cmd, primary=False, width=0.62, scale=0.06):
            c = (1.0, 0.55, 0.15, 1) if primary else (0.17, 0.19, 0.23, 0.95)
            h = (1.0, 0.68, 0.32, 1) if primary else (0.27, 0.3, 0.36, 1)

            def go():
                self.sounds.play("click", 0.6)
                cmd()
            return DirectButton(parent=parent, text=s, pos=(pos[0] + width / 2, 0, pos[1]), scale=scale, command=go,
                                text_font=self.font, text_fg=(0.1, 0.07, 0.03, 1) if primary else H.WHITE,
                                frameColor=(c, h, h, (0.2, 0.2, 0.2, 1)), relief=DGG.FLAT,
                                frameSize=(-width / 2 / scale, width / 2 / scale, -0.55, 1.05), pressEffect=0)

        def entry(self, parent, value, pos, width=12, secret=False):
            return DirectEntry(parent=parent, initialText=value, pos=pos, scale=0.05, width=width, numLines=1,
                               entryFont=self.font, text_fg=H.WHITE, frameColor=(0.08, 0.09, 0.11, 0.95),
                               relief=DGG.FLAT, obscured=secret, focusInCommand=lambda: None)

        def stepper(self, parent, label, y, get, set_, lo, hi):
            self.label(parent, label, (0.12, y), 0.045)
            val = self.label(parent, str(get()), (0.7, y), 0.05, H.WHITE, TextNode.ACenter)

            def ch(d):
                set_(max(lo, min(hi, get() + d)))
                val.setText(str(get()))
            self.button(parent, "-", (0.52, y + 0.012), lambda: ch(-1), width=0.09, scale=0.05)
            self.button(parent, "+", (0.79, y + 0.012), lambda: ch(1), width=0.09, scale=0.05)

        # ------------------------------------------------------------ screens
        def main_menu(self, message=None):
            fr = self.frame()
            self.label(fr, "LAST ARMORY", (0.12, 0.62), 0.15, H.ACCENT)
            self.label(fr, "Build guns. Sell guns. Survive the night.", (0.13, 0.52), 0.045, H.MUTED)
            self.label(fr, "Your name", (0.13, 0.38), 0.038, H.MUTED)
            name = self.entry(fr, self.settings["name"], (0.13, 0, 0.3), 12)

            def save_name():
                n = name.get().strip()[:16]
                if n:
                    self.settings["name"] = n
                    self.save_settings()

            def go(fn):
                return lambda: (save_name(), fn())
            self.button(fr, "Quick Play  (host + bots)", (0.12, 0.14), go(self.quick_play), primary=True, width=0.8)
            self.button(fr, "Join Server", (0.12, 0.02), go(self.join_menu), width=0.8)
            self.button(fr, "Host Server", (0.12, -0.1), go(self.host_menu), width=0.8)
            self.button(fr, "Settings", (0.12, -0.22), go(self.settings_menu), width=0.8)
            self.button(fr, "Quit", (0.12, -0.34), self.quit, width=0.8)
            mods = self.local["mods"]
            self.label(fr, f"v{VERSION}   -   {len(mods)} mod(s): " + ", ".join(m["name"] for m in mods),
                       (0.12, -0.9), 0.035, H.MUTED)
            for i, e in enumerate(self.local["errors"][:3]):
                self.label(fr, "Mod error: " + e, (0.12, -0.82 + i * 0.045), 0.032, H.BAD)
            if message:
                self.label(fr, message, (0.12, -0.5), 0.045, H.BAD)

        def quick_play(self):
            s = self.settings
            self.start_server(s["host_port"], s["host_min"], True, s["host_first"], f"{s['name']}'s game")
            self.connect("127.0.0.1", s["host_port"], hosting=True)

        def join_menu(self):
            fr = self.frame()
            self.label(fr, "JOIN SERVER", (0.12, 0.6), 0.1, H.ACCENT)
            self.label(fr, "Address (ip or ip:port)", (0.13, 0.45), 0.038, H.MUTED)
            addr = self.entry(fr, self.settings["last_address"], (0.13, 0, 0.37), 16)
            self.label(fr, "Password (optional)", (0.13, 0.27), 0.038, H.MUTED)
            pw = self.entry(fr, "", (0.13, 0, 0.19), 16, secret=True)

            def go(a=None):
                a = a or addr.get()
                h, p = parse_address(a)
                if not h:
                    return
                s = self.settings
                s["last_address"] = a
                s["recent"] = ([a] + [r for r in s["recent"] if r != a])[:5]
                self.save_settings()
                self.connect(h, p, pw.get())
            self.button(fr, "Connect", (0.12, 0.04), go, primary=True, width=0.5)
            self.button(fr, "Back", (0.66, 0.04), self.main_menu, width=0.3)
            y = -0.12
            for r in self.settings["recent"]:
                self.button(fr, r, (0.12, y), lambda r=r: go(r), width=0.84, scale=0.045)
                y -= 0.1
            self.label(fr, f"Default port {DEFAULT_PORT}. Internet play needs the host to forward that TCP port.",
                       (0.12, -0.85), 0.035, H.MUTED)

        def host_menu(self):
            fr = self.frame()
            s = self.settings
            self.label(fr, "HOST SERVER", (0.12, 0.6), 0.1, H.ACCENT)
            self.label(fr, "Server name", (0.13, 0.46), 0.038, H.MUTED)
            nm = self.entry(fr, s["host_name"] or f"{s['name']}'s server", (0.13, 0, 0.38), 16)
            self.label(fr, "Port", (0.13, 0.28), 0.038, H.MUTED)
            port = self.entry(fr, str(s["host_port"]), (0.13, 0, 0.2), 5)
            st = {"min": s["host_min"], "first": s["host_first"], "bots": s["host_bots"]}
            self.stepper(fr, "Fill with bots to", 0.06, lambda: st["min"], lambda v: st.__setitem__("min", v), 1, 8)
            self.stepper(fr, "Days per match", -0.06, lambda: st["first"], lambda v: st.__setitem__("first", v), 1, 15)

            def start():
                try:
                    p = int(port.get())
                except ValueError:
                    p = DEFAULT_PORT
                s.update(host_name=nm.get(), host_port=p, host_min=st["min"], host_first=st["first"])
                self.save_settings()
                self.start_server(p, st["min"], True, st["first"], nm.get())
                self.connect("127.0.0.1", p, hosting=True)
            self.button(fr, "Start & Join", (0.12, -0.22), start, primary=True, width=0.5)
            self.button(fr, "Back", (0.66, -0.22), self.main_menu, width=0.3)
            ip = lan_ip()
            for i, line in enumerate([f"Friends on your network join:  {ip}:{s['host_port']}",
                                      f"Internet: forward TCP port {s['host_port']} and share your public IP.",
                                      "24/7 server: run ArmoryServer and edit server_config.json."]):
                self.label(fr, line, (0.12, -0.42 - i * 0.06), 0.038, H.MUTED)

        def settings_menu(self):
            fr = self.frame()
            s = self.settings
            self.label(fr, "SETTINGS", (0.12, 0.6), 0.1, H.ACCENT)

            def slider(label, y, lo, hi, key, fmt):
                t = self.label(fr, "", (0.13, y), 0.045)

                def ch():
                    s[key] = sl["value"]
                    t.setText(f"{label}: {fmt(s[key])}")
                    if key == "volume":
                        self.sounds.volume = s[key]
                    if key == "fov":
                        self.camLens.setFov(s[key])
                sl = DirectSlider(parent=fr, range=(lo, hi), value=s[key], pos=(0.95, 0, y + 0.015), scale=0.3,
                                  command=ch, frameColor=(0.2, 0.22, 0.26, 1), thumb_frameColor=H.ACCENT)
                ch()
            slider("Mouse sensitivity", 0.42, 0.02, 0.5, "sens", lambda v: f"{v:.2f}")
            slider("Field of view", 0.3, 60, 110, "fov", lambda v: f"{v:.0f}")
            slider("Volume", 0.18, 0, 1, "volume", lambda v: f"{v * 100:.0f}%")
            self.button(fr, "Toggle fullscreen (F11)", (0.12, 0.02), self.toggle_fullscreen, width=0.8)

            def toggle_gfx():
                s["graphics"] = "compat" if s.get("graphics", "high") != "compat" else "high"
                self.save_settings()
                self.settings_menu()
            self.button(fr, f"Graphics: {'Compatible (restart)' if s.get('graphics') == 'compat' else 'High'}", (0.95, 0.02), toggle_gfx, width=0.8)
            self.button(fr, "Back", (0.12, -0.12), lambda: (self.save_settings(), self.main_menu()), primary=True, width=0.8)
            self.label(fr, f"Mods folder: {os.path.join(root, 'mods')}", (0.12, -0.32), 0.035, H.MUTED)
            self.label(fr, "Servers send their mods to players automatically.", (0.12, -0.38), 0.035, H.MUTED)

        def message(self, text):
            fr = self.frame()
            lines = str(text).split("\n")
            self.label(fr, lines[0], (0.12, 0.3), 0.07, H.WHITE)
            for i, l in enumerate(lines[1:]):
                self.label(fr, l, (0.12, 0.2 - i * 0.06), 0.04, H.MUTED)
            self.button(fr, "OK", (0.12, -0.1), self.main_menu, primary=True, width=0.4)

        # ------------------------------------------------------------ server/connection
        def start_server(self, port, min_players, bots, days, name):
            self.stop_server()
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--server"]  # the game binary doubles as a server
            else:
                cmd = [sys.executable, os.path.join(root, "LastArmory.py"), "--server"]
            cmd += ["--port", str(port), "--min-players", str(min_players), "--days", str(days), "--name", name or "Last Armory",
                    "--config", os.path.join(self.data_dir, "hosted_config.json")]
            if not bots:
                cmd.append("--no-bots")
            log = open(os.path.join(self.data_dir, "hosted_server.log"), "w", encoding="utf-8")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.server_proc = subprocess.Popen(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL, creationflags=flags)

        def stop_server(self):
            if self.server_proc and self.server_proc.poll() is None:
                self.server_proc.terminate()
                try:
                    self.server_proc.wait(3)
                except subprocess.TimeoutExpired:
                    self.server_proc.kill()
            self.server_proc = None

        def connect(self, host, port, password="", hosting=False):
            fr = self.frame()
            self.label(fr, "Starting server..." if hosting else "Connecting...", (0.12, 0.2), 0.08)
            self.label(fr, f"{host}:{port}", (0.12, 0.1), 0.045, H.MUTED)
            st = {"conn": None, "error": None, "cancel": False, "hosting": hosting, "t0": time.monotonic()}
            self.connecting = st

            def cancel():
                st["cancel"] = True
                if st["conn"]:
                    st["conn"].close()
                if hosting:
                    self.stop_server()
                self.connecting = None
                self.main_menu()
            self.button(fr, "Cancel", (0.12, -0.05), cancel, width=0.4)

            def worker():
                deadline = time.monotonic() + (12 if hosting else 0)
                while not st["cancel"]:
                    try:
                        c = Connection(host, port, 5)
                        break
                    except OSError as e:
                        if time.monotonic() < deadline:
                            time.sleep(0.25)
                            continue
                        st["error"] = f"Could not connect to {host}:{port}\n{e}"
                        return
                else:
                    return
                c.send({"t": "hello", "name": self.settings["name"], "protocol": PROTOCOL, "password": password})
                st["conn"] = c
            threading.Thread(target=worker, daemon=True).start()

        def connecting_tick(self):
            st = self.connecting
            if not st:
                return
            if st["error"]:
                self.connecting = None
                if st["hosting"]:
                    self.stop_server()
                    st["error"] += "\n(see userdata/hosted_server.log)"
                self.message(st["error"])
                return
            c = st["conn"]
            if c:
                msgs = c.poll()
                for i, m in enumerate(msgs):
                    if m.get("t") == "welcome":
                        self.connecting = None
                        self.clear_menu()
                        self.stop_showcase()

                        def leave(reason, hosting=st["hosting"]):
                            self.match.destroy()
                            self.match = None
                            if hosting:
                                self.stop_server()
                            self.main_menu()
                            if reason:
                                self.message(reason)
                        self.match = Match(self, c, m, leave)
                        for rest in msgs[i + 1:]:
                            self.match.handle(rest)
                        return
                    if m.get("t") == "kicked":
                        self.connecting = None
                        c.close()
                        self.message(m.get("reason", "Rejected by server"))
                        return
                if c.closed:
                    st["error"] = "Server closed the connection"
            if time.monotonic() - st["t0"] > 20:
                st["error"] = "Timed out"

        # ------------------------------------------------------------ loop
        def tick(self, task):
            dt = min(0.05, globalClock.getDt())  # noqa: F821 (Panda builtin)
            self.connecting_tick()
            if self.match:
                self.match.update(dt)
            else:
                self.showcase_tick(dt)
            return task.cont

    return App
