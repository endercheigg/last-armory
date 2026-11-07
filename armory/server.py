"""LAST ARMORY dedicated server. Authoritative, 30 Hz, newline-delimited JSON over TCP (stdlib only)."""
import asyncio
import json
import math
import os
import random
import socket
import sys
import threading
import time

from . import PROTOCOL, VERSION
from .content import client_payload, load_content
from .gun import SLOTS, auto_name, compute_stats, gun_value, validate
from .sim import (BASE_SPEED, BODY_H, BODY_R, EYE_H, HEAD_R, HEAD_Z, aim_vec, box_tuple, line_of_sight,
                  move_player, ray_box, ray_cylinder, ray_sphere, ray_world, spread_dir)
from .town import build_town

TICK = 30
DT = 1.0 / TICK
MAX_PLAYERS = 8
BASE_SHELVES = 3

DEFAULT_CONFIG = {
    "name": "Last Armory Server",
    "motd": "Build guns. Sell guns. Survive the night.",
    "port": 27030,
    "maxPlayers": 8,
    "password": "",
    "minPlayers": 4,
    "bots": True,
    "botSkill": 0.5,
    "days": 5,
    "daySeconds": 180,
    "nightSeconds": 100,
    "startCash": 400,
    "town": "",
    "arenas": [],
    "disabledMods": [],
}

BOT_NAMES = ["Rusty", "Sprocket", "Bolt", "Rivet", "Hammer", "Gasket", "Ratchet", "Piston", "Torque", "Flint"]
CUSTOMER_NAMES = ["Martha", "Old Joe", "Dina", "Sergei", "Pip", "Rosa", "Big Tom", "Yuki", "Abe", "Nell", "Hank",
                  "Iris", "Gus", "Mila", "Otto", "Faye", "Dutch", "Lena", "Moss", "Vik"]


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


class Body:
    """Anything that walks and can be shot (players and zombies)."""

    def __init__(self):
        self.s = {"x": 0.0, "y": 0.0, "z": 0.0, "vz": 0.0, "ground": True}
        self.h = 0.0
        self.p = 0.0
        self.hp = 100.0
        self.max_hp = 100.0
        self.alive = False

    @property
    def pos(self):
        return self.s["x"], self.s["y"], self.s["z"]


class Player(Body):
    def __init__(self, pid, name, writer=None, bot=False):
        super().__init__()
        self.id, self.name, self.writer, self.bot = pid, name, writer, bot
        self.color = pid % 8
        self.plot = 0
        self.cash = 0
        self.parts = {}
        self.guns = []
        self.shelf = []
        self.upgrades = {}
        self.stock = []
        self.held = None
        self.stats = {}
        self.kills = self.zkills = self.nights = 0
        self.earned = 0
        self.ammo = 0
        self.reload_until = 0.0
        self.next_shot = 0.0
        self.next_melee = 0.0
        self.bloom = 0.0
        self.inp = {"fire": 0, "clicks": 0, "reload": 0, "ads": 0, "melee": 0}
        self.clicks_used = 0
        self.melee_used = 0
        self.moves = []
        self.ack = 0
        self.moving = False
        self.last_hit_by = None
        self.speed_mul = 1.0
        self.damage_mul = 1.0
        self.data = {}
        self.inv_dirty = True
        # bot brain
        self.goal = None
        self.stuck = 0.0
        self.strafe = 1
        self.strafe_t = 0.0
        self.bot_fire_t = 0.0
        self.jump_t = 0.0
        self.think_t = 0.0

    def held_gun(self):
        return next((g for g in self.guns if g["id"] == self.held), None)


class Zombie(Body):
    def __init__(self, zid, ztype, index):
        super().__init__()
        self.id = zid
        self.type = ztype
        self.type_index = index
        self.hp = self.max_hp = float(ztype.get("hp", 60))
        self.alive = True
        self.next_hit = 0.0
        self.stuck = 0.0
        self.last = None


class Api:
    """Handed to mod hooks - see MODDING.md."""

    def __init__(self, game):
        self.game = game

    @property
    def config(self): return self.game.config
    @property
    def content(self): return self.game.content
    @property
    def phase(self): return self.game.phase
    @property
    def day(self): return self.game.day
    @property
    def time(self): return time.monotonic()

    def players(self, alive_only=False):
        return [p for p in self.game.players.values() if p.alive or not alive_only]

    def get_player(self, key):
        for p in self.game.players.values():
            if p.id == key or p.name.lower() == str(key).lower():
                return p
        return None

    def broadcast(self, text, color="#ffd75e"):
        self.game.chat_all(str(text), color)

    def tell(self, player, text, color="#9ad1ff"):
        self.game.send(player, {"t": "chat", "from": "", "msg": str(text), "color": color})

    def give_cash(self, player, amount, why=""):
        self.game.give_cash(player, amount, why)

    def give_part(self, player, part_id, count=1):
        if part_id in self.game.content["parts"]:
            player.parts[part_id] = player.parts.get(part_id, 0) + count
            player.inv_dirty = True

    def damage(self, player, amount, attacker=None):
        self.game.apply_damage(player, amount, attacker)

    def heal(self, player, amount):
        if player.alive:
            player.hp = min(player.max_hp, player.hp + amount)

    def spawn_zombie(self, type_id=None, x=None, y=None):
        return self.game.spawn_zombie(type_id, x, y)

    def log(self, *a):
        log("[mod]", *a)

    def command(self, name, help_text=""):
        def deco(fn):
            self.game.commands[name.lower()] = (fn, help_text)
            return fn
        return deco


class Game:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.players = {}
        self.next_id = 1
        self.next_gun = 1
        self.next_cust = 1
        self.next_zombie = 1
        self.commands = {}
        self.events = []
        self.dirty = True
        self.phase = "lobby"
        self.phase_end = 0.0
        self.start_at = 0.0
        self.day = 0
        self.customers = {}
        self.cust_t = 0.0
        self.zombies = {}
        self.wave_t = 0.0
        self.wave = 0
        self.arena = None
        self.arena_index = -1
        self.boxes = []
        self.winner_id = 0
        self.load()

    # ------------------------------------------------------------ content
    def load(self):
        c = load_content(os.path.join(self.root, "mods"), self.config.get("disabledMods", []))
        for e in c["errors"]:
            log("MOD ERROR:", e)
        if not (c["parts"] and c["towns"] and c["shops"] and c["arenas"]):
            raise SystemExit("Missing content - is mods/core there?")
        self.content = c
        self.world = build_town(c, self.config.get("town") or None)
        self.town_boxes = [box_tuple(b) for b in self.world["boxes"]]
        self.targets = self.world["targets"]
        self.start_kit = {p["slot"]: p["id"] for p in c["parts"].values() if p["start"]}
        log(f"Loaded {len(c['mods'])} mod(s): " + ", ".join(f"{m['name']} {m['version']}" for m in c["mods"]))
        log(f"{len(c['parts'])} parts, {len(c['upgrades'])} upgrades, {len(c['zombies'])} zombie types, "
            f"{len(c['arenas'])} arenas, town '{self.world['town'].get('name', '?')}' with {len(self.world['plots'])} shops")
        self.api = Api(self)
        self.commands = {}
        self.builtin_commands()
        self.hook("on_load")

    def hook(self, name, *args):
        result = None
        for mod in self.content["hooks"]:
            fn = getattr(mod, name, None)
            if fn:
                try:
                    r = fn(self.api, *args)
                    if r is not None:
                        result = r
                except Exception as e:
                    log(f"[{mod._mod_id}] error in {name}: {e!r}")
        return result

    def welcome(self, p):
        return {"t": "welcome", "id": p.id, "protocol": PROTOCOL, "version": VERSION,
                "server": {"name": self.config["name"], "motd": self.config["motd"], "days": self.config["days"]},
                "content": client_payload(self.content), "town": self.world["town"]["id"],
                "shop": self.world["shop"]["id"], "towns": self.content["towns"], "shops": self.content["shops"],
                "phase": self.phase_msg()}

    # ------------------------------------------------------------ economy helpers
    def effects(self, p):
        out = {}
        for uid, lvl in p.upgrades.items():
            u = self.content["upgrades"].get(uid)
            if not u:
                continue
            for L in u.get("levels", [])[:lvl]:
                for k, v in L.get("effects", {}).items():
                    out[k] = out.get(k, 0) + v
        return out

    def shelf_slots(self, p):
        return min(len(self.world["shop"]["shelves"]), BASE_SHELVES + int(self.effects(p).get("shelves", 0)))

    def give_cash(self, p, amount, why=""):
        amount = int(round(amount))
        p.cash += amount
        if amount > 0:
            p.earned += amount
        self.events.append({"t": "cash", "p": p.id, "n": amount, "why": why})
        self.dirty = True

    def make_gun(self, loadout, name=None):
        g = {"id": self.next_gun, "name": (name or auto_name(loadout, self.content["parts"], random))[:24],
             "parts": dict(loadout), "value": gun_value(loadout, self.content["parts"])}
        self.next_gun += 1
        return g

    def roll_stock(self, p):
        eff = self.effects(p)
        n = 6 + int(eff.get("stock", 0))
        disc = min(60, eff.get("discount", 0))
        parts = [q for q in self.content["parts"].values() if not q["start"] or q["slot"] in ("barrel", "magazine")]
        stock = []
        for _ in range(n):
            w = [50, 30, 14, 5, 1.2]
            w = [wt * (1 + 0.35 * max(0, self.day - 1) * t) for t, wt in enumerate(w)]
            tier = random.choices(range(5), weights=w)[0]
            pool = [q for q in parts if q["tier"] == tier] or parts
            slot_w = {"receiver": 2.2, "barrel": 1.6, "magazine": 1.3}
            part = random.choices(pool, weights=[slot_w.get(q["slot"], 1) for q in pool])[0]
            price = int(round(part["price"] * random.uniform(0.85, 1.2) * (1 - disc / 100)))
            stock.append({"pid": part["id"], "price": max(1, price)})
        p.stock = stock
        p.inv_dirty = True

    # ------------------------------------------------------------ players
    def add_player(self, name, writer=None, bot=False):
        p = Player(self.next_id, name, writer, bot)
        self.next_id += 1
        used_c = {o.color for o in self.players.values()}
        p.color = next((c for c in range(8) if c not in used_c), p.id % 8)
        used_p = {o.plot for o in self.players.values()}
        p.plot = next((i for i in range(len(self.world["plots"])) if i not in used_p), 0)
        self.players[p.id] = p
        self.reset_player(p)
        if self.phase == "day":
            self.roll_stock(p)
            self.place_in_shop(p)
        self.dirty = True
        return p

    def reset_player(self, p):
        p.cash = self.config["startCash"]
        p.parts = {}
        for pid in self.start_kit.values():
            p.parts[pid] = p.parts.get(pid, 0) + 1
        starter = self.make_gun(self.start_kit, "Old Faithful")
        p.guns = [starter]
        p.held = starter["id"]
        p.shelf = [None] * len(self.world["shop"]["shelves"])
        p.upgrades = {}
        p.kills = p.zkills = p.nights = p.earned = 0
        p.inv_dirty = True
        self.restat(p)

    def restat(self, p):
        g = p.held_gun()
        p.stats = compute_stats(g["parts"] if g else self.start_kit, self.content["parts"])
        p.ammo = min(p.ammo, p.stats["magSize"]) if p.ammo else p.stats["magSize"]
        self.dirty = True

    def remove_player(self, p):
        if self.players.pop(p.id, None):
            self.dirty = True
            for c in list(self.customers.values()):
                if c["plot"] == p.plot:
                    self.customer_leave(c, "Shop closed")
            self.hook("on_player_leave", p)
            if not p.bot:
                self.chat_all(f"{p.name} left")
            if self.phase == "night":
                self.check_night_end()

    def humans(self):
        return [p for p in self.players.values() if not p.bot]

    def balance_bots(self):
        want = 0
        if self.config["bots"] and self.humans():
            want = max(0, min(MAX_PLAYERS, len(self.world["plots"]), self.config["minPlayers"]) - len(self.humans()))
        bots = [p for p in self.players.values() if p.bot]
        while len(bots) < want:
            used = {p.name for p in self.players.values()}
            n = next((n for n in BOT_NAMES if f"[BOT] {n}" not in used), f"Bot{self.next_id}")
            bots.append(self.add_player(f"[BOT] {n}", bot=True))
        while len(bots) > want:
            self.remove_player(bots.pop())

    def place_in_shop(self, p):
        sp = self.world["plots"][p.plot]["spawn"]
        p.s = {"x": sp[0], "y": sp[1], "z": 0.0, "vz": 0.0, "ground": True}
        p.h = sp[3]
        p.p = 0.0
        p.alive = True
        p.hp = p.max_hp = 100.0
        p.moves.clear()
        p.reload_until = 0.0
        p.ammo = p.stats.get("magSize", 10)
        self.send(p, {"t": "tp", "x": p.s["x"], "y": p.s["y"], "z": 0, "h": p.h})

    # ------------------------------------------------------------ phases
    def phase_msg(self):
        now = time.monotonic()
        m = {"t": "phase", "phase": self.phase, "day": self.day, "left": round(max(0, self.phase_end - now), 1),
             "start_in": round(max(0, self.start_at - now), 1)}
        if self.phase == "night":
            m["arena"] = self.arena
        if self.phase == "results":
            m["winner"] = self.winner_id
        return m

    def set_phase(self, ph, dur):
        self.phase = ph
        self.phase_end = time.monotonic() + dur
        self.send_all(self.phase_msg())
        self.hook("on_phase", ph)
        self.dirty = True

    def start_match(self):
        self.day = 0
        for p in self.players.values():
            self.reset_player(p)
        self.start_day()

    def start_day(self):
        self.day += 1
        self.zombies.clear()
        self.customers.clear()
        self.cust_t = 2.0
        self.start_at = time.monotonic()
        for p in self.players.values():
            self.roll_stock(p)
            self.restat(p)
            self.place_in_shop(p)
        self.hook("on_day_start", self.day)
        self.set_phase("day", self.config["daySeconds"])
        self.chat_all(f"Day {self.day} of {self.config['days']} - the shops are open!", "#ffd75e")
        log(f"Day {self.day}")

    def start_night(self):
        for c in list(self.customers.values()):
            del self.customers[c["id"]]
        ids = list(self.content["arenas"])
        rot = [a for a in self.config.get("arenas") or [] if a in self.content["arenas"]] or ids
        self.arena_index = (self.arena_index + 1) % len(rot)
        self.arena = self.content["arenas"][rot[self.arena_index]]
        self.boxes = [box_tuple(b) for b in self.arena.get("boxes", [])]
        spawns = list(self.arena["spawns"])
        random.shuffle(spawns)
        for i, p in enumerate(self.players.values()):
            sp = spawns[i % len(spawns)]
            self.restat(p)
            eff = self.effects(p)
            p.max_hp = 100.0 + eff.get("maxHp", 0)
            p.hp = p.max_hp
            p.alive = True
            p.s = {"x": float(sp[0]), "y": float(sp[1]), "z": float(sp[2]), "vz": 0.0, "ground": False}
            p.h, p.p = float(sp[3]) if len(sp) > 3 else 0.0, 0.0
            p.ammo = p.stats["magSize"]
            p.reload_until = 0.0
            p.moves.clear()
            p.last_hit_by = None
            p.goal = None
            self.send(p, {"t": "tp", "x": p.s["x"], "y": p.s["y"], "z": p.s["z"], "h": p.h})
        self.zombies.clear()
        self.wave = 0
        self.wave_t = 4.0
        self.start_at = time.monotonic() + 4
        self.hook("on_night_start", self.day)
        self.set_phase("night", 4 + self.config["nightSeconds"])
        log(f"Night {self.day}: {self.arena.get('name', self.arena['id'])}")

    def end_night(self, winner):
        alive = [p for p in self.players.values() if p.alive]
        if winner:
            winner.nights += 1
            self.give_cash(winner, 250, "Last one standing!")
            self.chat_all(f"{winner.name} survived the night and takes the $250 bounty!", "#ffb347")
        else:
            for p in alive:
                self.give_cash(p, 100, "Survived the night")
        self.zombies.clear()
        if self.day >= self.config["days"]:
            best = max(self.players.values(), key=lambda p: p.cash, default=None)
            self.winner_id = best.id if best else 0
            if best:
                self.chat_all(f"{best.name} is the richest gunsmith with ${best.cash}!", "#ffb347")
            self.hook("on_match_end", best)
            self.set_phase("results", 15)
        else:
            self.set_phase("dawn", 4)

    def check_night_end(self):
        if self.phase != "night":
            return
        alive = [p for p in self.players.values() if p.alive]
        if len(alive) <= 1 and len(self.players) > 1:
            self.end_night(alive[0] if alive else None)
        elif not alive:
            self.end_night(None)

    # ------------------------------------------------------------ actions
    def in_own_shop(self, p):
        c = self.world["plots"][p.plot]["center"]
        return math.hypot(p.s["x"] - c[0], p.s["y"] - c[1]) < 14

    def act(self, p, m):
        a = m.get("a")
        if self.phase != "day":
            return self.fail(p, "The shops are closed at night")
        parts = self.content["parts"]
        if a == "buy_part":
            i = m.get("i")
            if not isinstance(i, int) or not (0 <= i < len(p.stock)) or not p.stock[i]:
                return
            if not self.in_own_shop(p) and not p.bot:
                return self.fail(p, "Use the supply terminal in your shop")
            off = p.stock[i]
            if p.cash < off["price"]:
                return self.fail(p, "Not enough cash")
            p.cash -= off["price"]
            p.parts[off["pid"]] = p.parts.get(off["pid"], 0) + 1
            p.stock[i] = None
            self.events.append({"t": "cash", "p": p.id, "n": -off["price"], "why": f"Bought {parts[off['pid']]['name']}"})
        elif a == "craft":
            lo = m.get("parts")
            err = validate(lo, parts)
            if err:
                return self.fail(p, f"Can't assemble: {err}")
            need = {}
            for pid in lo.values():
                need[pid] = need.get(pid, 0) + 1
            if any(p.parts.get(pid, 0) < n for pid, n in need.items()):
                return self.fail(p, "You don't have those parts")
            for pid, n in need.items():
                p.parts[pid] -= n
                if p.parts[pid] <= 0:
                    del p.parts[pid]
            name = str(m.get("name") or "").strip()[:24] or None
            g = self.make_gun(lo, name)
            p.guns.append(g)
            if not p.held_gun():
                p.held = g["id"]
            self.events.append({"t": "crafted", "p": p.id, "gun": g})
            self.hook("on_craft", p, g)
        elif a == "disassemble":
            if not self.effects(p).get("disassemble") and not p.bot:
                return self.fail(p, "Upgrade your workbench to disassemble guns")
            g = next((g for g in p.guns if g["id"] == m.get("gid")), None)
            if not g:
                return
            p.guns.remove(g)
            for pid in g["parts"].values():
                p.parts[pid] = p.parts.get(pid, 0) + 1
            if p.held == g["id"]:
                p.held = p.guns[0]["id"] if p.guns else None
        elif a == "shelve":
            slot, gid, price = m.get("slot"), m.get("gid"), m.get("price")
            if not isinstance(slot, int) or not (0 <= slot < self.shelf_slots(p)) or p.shelf[slot]:
                return self.fail(p, "That shelf isn't free")
            g = next((g for g in p.guns if g["id"] == gid), None)
            if not g or not isinstance(price, int) or not (1 <= price <= 999999):
                return
            if len(p.guns) <= 1 and not p.bot:
                return self.fail(p, "Keep at least one gun for the night!")
            p.guns.remove(g)
            if p.held == g["id"]:
                p.held = p.guns[0]["id"] if p.guns else None
            p.shelf[slot] = {"gun": g, "price": price}
        elif a == "unshelve":
            slot = m.get("slot")
            if isinstance(slot, int) and 0 <= slot < len(p.shelf) and p.shelf[slot]:
                p.guns.append(p.shelf[slot]["gun"])
                p.shelf[slot] = None
        elif a == "reprice":
            slot, price = m.get("slot"), m.get("price")
            if isinstance(slot, int) and 0 <= slot < len(p.shelf) and p.shelf[slot] and isinstance(price, int) and 1 <= price <= 999999:
                p.shelf[slot]["price"] = price
        elif a == "upgrade":
            u = self.content["upgrades"].get(m.get("id"))
            if not u:
                return
            lvl = p.upgrades.get(u["id"], 0)
            levels = u.get("levels", [])
            if lvl >= len(levels):
                return self.fail(p, "Already maxed")
            cost = levels[lvl]["cost"]
            if p.cash < cost:
                return self.fail(p, "Not enough cash")
            p.cash -= cost
            p.upgrades[u["id"]] = lvl + 1
            self.events.append({"t": "cash", "p": p.id, "n": -cost, "why": f"{u['name']} level {lvl + 1}"})
            if "stock" in levels[lvl].get("effects", {}):
                for _ in range(int(levels[lvl]["effects"]["stock"])):
                    p.stock.append(None)
        elif a == "buy_gun":
            o = self.players.get(m.get("owner"))
            slot = m.get("slot")
            if not o or o is p or not isinstance(slot, int) or not (0 <= slot < len(o.shelf)) or not o.shelf[slot]:
                return
            sx, sy, _, _ = self.world["plots"][o.plot]["shelves"][slot]
            if math.hypot(p.s["x"] - sx, p.s["y"] - sy) > 4.5:
                return self.fail(p, "Walk up to the shelf")
            item = o.shelf[slot]
            if p.cash < item["price"]:
                return self.fail(p, "Not enough cash")
            p.cash -= item["price"]
            o.shelf[slot] = None
            p.guns.append(item["gun"])
            o.inv_dirty = True
            self.give_cash(o, item["price"], f"{p.name} bought {item['gun']['name']}")
            self.events.append({"t": "cash", "p": p.id, "n": -item["price"], "why": f"Bought {item['gun']['name']}"})
            self.events.append({"t": "sale", "seller": o.id, "buyer": p.name, "gun": item["gun"]["name"], "price": item["price"]})
            self.hook("on_sale", o, p.name, item["gun"], item["price"])
        elif a == "hold":
            if any(g["id"] == m.get("gid") for g in p.guns):
                p.held = m.get("gid")
                self.restat(p)
        else:
            return
        p.inv_dirty = True
        self.dirty = True

    def fail(self, p, text):
        self.send(p, {"t": "toast", "msg": text, "bad": 1})

    # ------------------------------------------------------------ customers
    def spawn_customer(self):
        shops = [p for p in self.players.values()]
        if not shops:
            return
        weights = []
        for p in shops:
            eff = self.effects(p)
            listed = sum(1 for s in p.shelf[:self.shelf_slots(p)] if s)
            weights.append((0.3 + listed) * (1 + 0.5 * eff.get("attract", 0)) * (1 + 0.7 * eff.get("signs", 0)))
        shop = random.choices(shops, weights=weights)[0]
        prefs = list(self.content["customers"].values())
        pref = random.choices(prefs, weights=[x.get("weight", 10) for x in prefs])[0] if prefs else None
        budget = random.uniform(70, 170) * (1 + 0.5 * (self.day - 1))
        if random.random() < 0.12:
            budget *= 2.5
        gate = random.choice(self.world["gates"])
        plot = self.world["plots"][shop.plot]
        c = {"id": self.next_cust, "name": random.choice(CUSTOMER_NAMES), "plot": shop.plot, "owner": shop.id,
             "x": float(gate[0]), "y": float(gate[1]), "h": 0.0, "pref": pref["id"] if pref else None,
             "budget": int(budget), "tol": random.uniform(1.0, 1.3), "state": "walk", "t": 0.0,
             "wp": [plot["outside"][:2], plot["door"][:2], random.choice(plot["browse"])[:2]], "speed": random.uniform(3.0, 3.8),
             "look": random.randrange(8)}
        self.next_cust += 1
        self.hook("on_customer", c)
        self.customers[c["id"]] = c
        self.events.append({"t": "cust", "id": c["id"], "name": c["name"], "pref": c["pref"], "budget": c["budget"], "look": c["look"]})

    def customer_decide(self, c):
        owner = self.players.get(c["owner"])
        if not owner:
            return self.customer_leave(c, "...")
        pref = self.content["customers"].get(c["pref"])
        best, best_score = None, 0
        for slot, item in enumerate(owner.shelf[:self.shelf_slots(owner)]):
            if not item:
                continue
            st = compute_stats(item["gun"]["parts"], self.content["parts"])
            match = 1.0
            if pref:
                v = max(1e-3, st.get(pref["stat"], 1))
                match = (pref["ref"] / v) if pref.get("lower") else (v / pref["ref"])
                match = max(0.3, min(2.2, match))
            worth = item["gun"]["value"] * (0.75 + 0.45 * match)
            if item["price"] <= c["budget"] and item["price"] <= worth * c["tol"]:
                score = worth - item["price"] + 1
                if score > best_score:
                    best, best_score = slot, score
        if best is None:
            listed = any(owner.shelf[:self.shelf_slots(owner)])
            return self.customer_leave(c, "Too pricey!" if listed else "Nothing to buy!")
        item = owner.shelf[best]
        owner.shelf[best] = None
        owner.inv_dirty = True
        self.give_cash(owner, item["price"], f"Sold {item['gun']['name']} to {c['name']}")
        self.events.append({"t": "sale", "seller": owner.id, "buyer": c["name"], "gun": item["gun"]["name"], "price": item["price"]})
        self.hook("on_sale", owner, c["name"], item["gun"], item["price"])
        self.customer_leave(c, "Bought it!", True)

    def customer_leave(self, c, text, happy=False):
        plot = self.world["plots"][c["plot"]]
        gate = min(self.world["gates"], key=lambda g: math.hypot(g[0] - c["x"], g[1] - c["y"]))
        c["state"] = "leave"
        c["wp"] = [plot["door"][:2], plot["outside"][:2], list(gate)]
        self.events.append({"t": "cb", "id": c["id"], "text": text, "happy": 1 if happy else 0})

    def customers_tick(self, now):
        self.cust_t -= DT
        cap = 3 * max(1, len(self.players))
        if self.cust_t <= 0 and len(self.customers) < cap and now - self.start_at > 3:
            self.spawn_customer()
            self.cust_t = max(1.3, 5.0 - 0.45 * self.day) * random.uniform(0.6, 1.4) * 4 / max(2, len(self.players))
        for c in list(self.customers.values()):
            if c["state"] == "browse":
                c["t"] -= DT
                if c["t"] <= 0:
                    self.customer_decide(c)
                continue
            if not c["wp"]:
                if c["state"] == "walk":
                    c["state"] = "browse"
                    c["t"] = random.uniform(2.0, 3.5)
                else:
                    del self.customers[c["id"]]
                continue
            tx, ty = c["wp"][0]
            dx, dy = tx - c["x"], ty - c["y"]
            d = math.hypot(dx, dy)
            step = c["speed"] * DT
            if d <= step:
                c["x"], c["y"] = tx, ty
                c["wp"].pop(0)
            else:
                c["x"] += dx / d * step
                c["y"] += dy / d * step
                c["h"] = math.degrees(math.atan2(-dx, dy))

    # ------------------------------------------------------------ bots (day)
    def bot_day(self, p, now):
        if now < p.think_t:
            return
        p.think_t = now + random.uniform(1.5, 3.0)
        parts = self.content["parts"]
        have = {}
        for pid, n in p.parts.items():
            have.setdefault(parts[pid]["slot"], []).append(pid)
        reserve = 60 + 25 * self.day
        for i, off in enumerate(p.stock):
            if not off or p.cash - off["price"] < reserve:
                continue
            slot = parts[off["pid"]]["slot"]
            need = slot in ("receiver", "barrel", "magazine") and slot not in have
            if need or random.random() < 0.35:
                self.act(p, {"a": "buy_part", "i": i})
                have.setdefault(slot, []).append(off["pid"])
                break
        if all(s in have for s in ("receiver", "barrel", "magazine")):
            lo = {}
            for slot, pids in have.items():
                lo[slot] = max(pids, key=lambda q: parts[q]["tier"])
            self.act(p, {"a": "craft", "parts": lo})
        if p.guns:
            best = max(p.guns, key=lambda g: g["value"])
            if p.held != best["id"]:
                self.act(p, {"a": "hold", "gid": best["id"]})
            for g in [g for g in p.guns if g["id"] != p.held]:
                free = [i for i in range(self.shelf_slots(p)) if not p.shelf[i]]
                if not free:
                    break
                self.act(p, {"a": "shelve", "slot": free[0], "gid": g["id"], "price": int(g["value"] * random.uniform(1.1, 1.4))})
        if random.random() < 0.3:
            ups = []
            for u in self.content["upgrades"].values():
                lvl = p.upgrades.get(u["id"], 0)
                if lvl < len(u.get("levels", [])) and p.cash > u["levels"][lvl]["cost"] * 2 + reserve:
                    ups.append(u["id"])
            if ups:
                self.act(p, {"a": "upgrade", "id": random.choice(ups)})

    # ------------------------------------------------------------ combat (shared by day range + night)
    def world_boxes(self):
        return self.boxes if self.phase == "night" else self.town_boxes

    def try_fire(self, p, now):
        st = p.stats
        if now < p.reload_until or now < p.next_shot:
            return
        if p.ammo <= 0:
            p.reload_until = now + st["reloadTime"]
            p.ammo = st["magSize"]
            return
        wants = p.inp["fire"] if st["auto"] else p.inp["clicks"] > p.clicks_used
        if not wants:
            return
        p.clicks_used = p.inp["clicks"]
        p.next_shot = now + 1.0 / st["fireRate"]
        p.ammo -= 1
        cone = st["spread"] + p.bloom
        if p.moving or not p.s["ground"]:
            cone *= 1.5
        if p.inp["ads"]:
            cone *= 0.55
        p.bloom = min(12, p.bloom + st["recoil"])
        o = (p.s["x"], p.s["y"], p.s["z"] + EYE_H)
        boxes = self.world_boxes()
        ends, hits = [], {}
        max_t = st["range"] * 1.6
        night = self.phase == "night"
        for _ in range(st["pellets"]):
            d = spread_dir(p.h, p.p, cone)
            t, _w = ray_world(o, d, boxes, max_t)
            victim, head, tgt = None, False, None
            if night:
                for q in list(self.players.values()) + list(self.zombies.values()):
                    if q is p or not q.alive:
                        continue
                    qx, qy, qz = q.pos
                    sc = q.type.get("scale", 1.0) if isinstance(q, Zombie) else 1.0
                    th = ray_sphere(o, d, (qx, qy, qz + HEAD_Z * sc), HEAD_R * sc)
                    tb = ray_cylinder(o, d, qx, qy, qz, qz + BODY_H * sc, BODY_R * sc)
                    for tt, hd in ((th, True), (tb, False)):
                        if tt is not None and tt < t:
                            t, victim, head = tt, q, hd
            else:
                for tg in self.targets:
                    if tg["plot"] != p.plot:
                        continue
                    tt = ray_box(o, d, tg["box"])
                    if tt is not None and tt < t:
                        t, tgt = tt, tg
            end = (o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t)
            kind = 0 if victim is None else (2 if head else 1)
            if t >= max_t - 1e-3:
                kind = -1
            if tgt:
                kind = 3
            ends.append([round(end[0], 2), round(end[1], 2), round(end[2], 2), kind])
            fall = 1.0 if t <= st["range"] else max(0.0, 1 - (t - st["range"]) / (st["range"] * 0.6))
            dmg = st["damage"] * fall * (st["headshot"] if head else 1.0) * p.damage_mul
            if victim:
                h = hits.setdefault(id(victim), [victim, 0.0, False])
                h[1] += dmg
                h[2] = h[2] or head
            if tgt:
                self.events.append({"t": "thit", "p": p.id, "i": tgt["idx"], "plot": tgt["plot"], "n": round(dmg)})
            if night and st["explosionRadius"] > 0 and kind != -1:
                self.explode(end, st["explosionRadius"], st["damage"] * 0.8 * p.damage_mul, p, skip=victim)
        self.events.append({"t": "shot", "p": p.id, "o": [round(o[0], 2), round(o[1], 2), round(o[2], 2)], "e": ends})
        for victim, dmg, head in hits.values():
            self.apply_damage(victim, dmg, p, head=head)

    def try_melee(self, p, now):
        if p.inp["melee"] <= p.melee_used or now < p.next_melee:
            return
        p.melee_used = p.inp["melee"]
        p.next_melee = now + 0.6
        self.events.append({"t": "melee", "p": p.id})
        if self.phase != "night":
            return
        fx, fy, _ = aim_vec(p.h, 0)
        best, bd = None, 2.3
        for q in list(self.players.values()) + list(self.zombies.values()):
            if q is p or not q.alive:
                continue
            dx, dy = q.s["x"] - p.s["x"], q.s["y"] - p.s["y"]
            d = math.hypot(dx, dy)
            if d < bd and (dx * fx + dy * fy) / max(1e-3, d) > 0.5 and abs(q.s["z"] - p.s["z"]) < 1.5:
                best, bd = q, d
        if best:
            self.apply_damage(best, p.stats.get("melee", 20) * p.damage_mul, p)

    def explode(self, c, radius, damage, owner, skip=None):
        self.events.append({"t": "boom", "x": round(c[0], 2), "y": round(c[1], 2), "z": round(c[2], 2), "r": radius})
        for q in list(self.players.values()) + list(self.zombies.values()):
            if not q.alive or q is skip:
                continue
            qc = (q.s["x"], q.s["y"], q.s["z"] + 1.0)
            dist = math.dist(qc, c)
            if dist > radius + 0.5 or not line_of_sight(c, qc, self.boxes):
                continue
            amt = damage * (1 - 0.7 * min(1, dist / radius))
            if q is owner:
                amt *= 0.5
            self.apply_damage(q, amt, owner)

    def apply_damage(self, victim, amount, attacker, head=False, force=False):
        if not victim.alive or self.phase != "night":
            return
        if isinstance(victim, Zombie):
            victim.hp -= amount
            self.events.append({"t": "dmg", "v": -victim.id, "a": attacker.id if attacker else 0, "n": round(amount), "hd": 1 if head else 0})
            if victim.hp <= 0:
                victim.alive = False
                del self.zombies[victim.id]
                if attacker and isinstance(attacker, Player):
                    attacker.zkills += 1
                    reward = victim.type.get("reward", 15)
                    self.give_cash(attacker, reward, f"{victim.type.get('name', 'Zombie')} killed")
                    self.hook("on_zombie_kill", victim, attacker)
                self.events.append({"t": "zdead", "id": victim.id})
            return
        ev = {"victim": victim, "attacker": attacker, "amount": amount, "head": head, "cancel": False}
        if not force:
            self.hook("on_damage", ev)
            if ev["cancel"]:
                return
        amount = max(0.0, ev["amount"])
        victim.hp -= amount
        if isinstance(attacker, Player) and attacker is not victim:
            victim.last_hit_by = attacker.id
        self.events.append({"t": "dmg", "v": victim.id, "a": attacker.id if isinstance(attacker, Player) else 0,
                            "n": round(amount), "hd": 1 if head else 0})
        if victim.hp <= 0:
            victim.hp = 0
            victim.alive = False
            killer = attacker if isinstance(attacker, Player) and attacker is not victim else self.players.get(victim.last_hit_by)
            gun = ""
            if killer:
                killer.kills += 1
                loot = int(min(victim.cash * 0.25, 500))
                if loot > 0:
                    victim.cash -= loot
                    self.events.append({"t": "cash", "p": victim.id, "n": -loot, "why": f"Looted by {killer.name}"})
                    self.give_cash(killer, loot, f"Looted {victim.name}")
                g = killer.held_gun()
                gun = g["name"] if g else ""
            self.events.append({"t": "kill", "k": killer.id if killer else 0, "v": victim.id, "gun": gun,
                                "z": 1 if isinstance(attacker, Zombie) else 0})
            self.dirty = True
            self.hook("on_kill", victim, killer)
            self.check_night_end()

    # ------------------------------------------------------------ zombies
    def spawn_zombie(self, type_id=None, x=None, y=None):
        types = [z for z in self.content["zombies"].values() if z.get("minDay", 1) <= max(1, self.day)] \
            or list(self.content["zombies"].values())
        if not types or not self.arena:
            return None
        zt = self.content["zombies"].get(type_id) if type_id else random.choices(types, weights=[z.get("weight", 10) for z in types])[0]
        index = list(self.content["zombies"]).index(zt["id"])
        z = Zombie(self.next_zombie, zt, index)
        self.next_zombie += 1
        if x is None:
            sp = random.choice(self.arena.get("zspawns") or self.arena["spawns"])
            x, y = sp[0] + random.uniform(-1, 1), sp[1] + random.uniform(-1, 1)
        z.s.update(x=float(x), y=float(y), z=0.0)
        hp_mul = 1 + 0.15 * (self.day - 1)
        z.hp = z.max_hp = zt.get("hp", 60) * hp_mul
        self.zombies[z.id] = z
        return z

    def zombies_tick(self, now):
        self.wave_t -= DT
        if self.wave_t <= 0 and len(self.zombies) < 40:
            self.wave += 1
            for _ in range(2 + self.day + self.wave):
                self.spawn_zombie()
            self.wave_t = max(6.0, 14 - self.day)
        size = self.arena["size"]
        alive = [p for p in self.players.values() if p.alive]
        for z in list(self.zombies.values()):
            if not alive:
                break
            tgt = min(alive, key=lambda p: math.hypot(p.s["x"] - z.s["x"], p.s["y"] - z.s["y"]))
            dx, dy = tgt.s["x"] - z.s["x"], tgt.s["y"] - z.s["y"]
            d = math.hypot(dx, dy)
            z.h = math.degrees(math.atan2(-dx, dy))
            if d < 1.25 and abs(tgt.s["z"] - z.s["z"]) < 1.6:
                if now >= z.next_hit:
                    z.next_hit = now + 1.0
                    self.apply_damage(tgt, z.type.get("damage", 12), z)
                continue
            jump = 0
            if z.last and math.hypot(z.s["x"] - z.last[0], z.s["y"] - z.last[1]) < 0.01:
                z.stuck += DT
                jump = 1
                if z.stuck > 1.5:
                    z.h += random.choice((-70, 70))
            else:
                z.stuck = 0
            z.last = (z.s["x"], z.s["y"])
            move_player(z.s, 1, 0, jump, z.h, z.type.get("speed", 3.0), DT, self.boxes, size)

    # ------------------------------------------------------------ bots (night)
    def bot_night(self, p, now):
        skill = self.config["botSkill"]
        eye = (p.s["x"], p.s["y"], p.s["z"] + EYE_H)
        target, best = None, 1e9
        for q in list(self.players.values()) + list(self.zombies.values()):
            if q is p or not q.alive:
                continue
            d = math.dist(p.pos, q.pos) * (0.8 if isinstance(q, Zombie) else 1.0)
            if d < best and line_of_sight(eye, (q.s["x"], q.s["y"], q.s["z"] + 1.2), self.boxes):
                target, best = q, d
        fwd = strafe = jump = 0
        if target:
            dx, dy = target.s["x"] - p.s["x"], target.s["y"] - p.s["y"]
            dz = (target.s["z"] + 1.1) - (p.s["z"] + EYE_H)
            want_h = math.degrees(math.atan2(-dx, dy))
            want_p = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
            err = (1 - skill) * 7
            dh = (want_h + random.gauss(0, err) - p.h + 180) % 360 - 180
            p.h += dh * min(1, 0.25 + skill * 0.5)
            p.p += (want_p + random.gauss(0, err * 0.5) - p.p) * 0.5
            if now > p.strafe_t:
                p.strafe = random.choice((-1, 1))
                p.strafe_t = now + random.uniform(0.5, 1.6)
            ideal = 6 if isinstance(target, Zombie) else p.stats["range"] * 0.5
            fwd = 1 if best > ideal + 4 else -1 if best < ideal - 3 else 0
            strafe = p.strafe
            aimed = abs(dh) < 6
            if p.stats["auto"]:
                p.inp["fire"] = 1 if aimed else 0
            elif aimed and now > p.bot_fire_t:
                p.inp["clicks"] += 1
                p.bot_fire_t = now + 1 / p.stats["fireRate"] + random.uniform(0.05, 0.35) * (1.2 - skill)
            if best < 2:
                p.inp["melee"] += 1
        else:
            p.inp["fire"] = 0
            size = self.arena["size"]
            if not p.goal or math.hypot(p.goal[0] - p.s["x"], p.goal[1] - p.s["y"]) < 2 or p.stuck > 2:
                others = [q for q in self.players.values() if q.alive and q is not p]
                if others and random.random() < 0.7:
                    q = random.choice(others)
                    p.goal = (q.s["x"], q.s["y"])
                else:
                    p.goal = (random.uniform(2, size[0] - 2), random.uniform(2, size[1] - 2))
                p.stuck = 0
            dx, dy = p.goal[0] - p.s["x"], p.goal[1] - p.s["y"]
            want = math.degrees(math.atan2(-dx, dy))
            p.h += ((want - p.h + 180) % 360 - 180) * 0.3
            p.p *= 0.8
            fwd = 1
        if now > p.jump_t:
            jump = 1 if random.random() < 0.25 else 0
            p.jump_t = now + random.uniform(1, 3)
        last = p.data.get("_lastpos")
        if last and math.hypot(p.s["x"] - last[0], p.s["y"] - last[1]) < 0.02 and fwd:
            p.stuck += DT
            jump = 1
        p.data["_lastpos"] = (p.s["x"], p.s["y"])
        return fwd, strafe, jump

    # ------------------------------------------------------------ tick
    def move_tick(self, now, frozen):
        night = self.phase == "night"
        boxes = self.world_boxes()
        size = self.arena["size"] if night else self.world["size"]
        for p in list(self.players.values()):
            if not p.alive:
                continue
            speed = BASE_SPEED * p.stats["moveSpeed"] * p.speed_mul
            if p.bot:
                if night and not frozen:
                    fwd, strafe, jump = self.bot_night(p, now)
                    move_player(p.s, fwd, strafe, jump, p.h, speed, DT, boxes, size)
                    p.moving = bool(fwd or strafe)
                elif not night:
                    self.bot_day(p, now)
            else:
                if len(p.moves) > 4:
                    del p.moves[:len(p.moves) - 2]
                if p.moves:
                    seq, fwd, strafe, jump, h = p.moves.pop(0)
                    p.ack = seq
                    if frozen:
                        fwd = strafe = jump = 0
                    move_player(p.s, fwd, strafe, jump, h, speed, DT, boxes, size)
                    p.moving = bool(fwd or strafe)
                else:
                    move_player(p.s, 0, 0, 0, p.h, speed, DT, boxes, size)
                    p.moving = False
            p.bloom = max(0.0, p.bloom - 8 * DT)
            if p.reload_until and now >= p.reload_until:
                p.reload_until = 0.0
            if p.inp["reload"] and not p.reload_until and p.ammo < p.stats["magSize"]:
                p.reload_until = now + p.stats["reloadTime"]
                p.ammo = p.stats["magSize"]
            p.inp["reload"] = 0
            if not frozen:
                self.try_fire(p, now)
                self.try_melee(p, now)

    def tick(self):
        now = time.monotonic()
        ph = self.phase
        if ph == "lobby":
            if self.humans():
                if not self.phase_end:
                    self.balance_bots()
                    self.set_phase("lobby", 6)
                elif now >= self.phase_end:
                    self.start_match()
            else:
                self.phase_end = 0.0
        elif ph == "day":
            self.move_tick(now, False)
            self.customers_tick(now)
            if now >= self.phase_end:
                self.start_night()
        elif ph == "night":
            frozen = now < self.start_at
            self.move_tick(now, frozen)
            if not frozen:
                self.zombies_tick(now)
            if now >= self.phase_end and self.phase == "night":
                self.chat_all("Dawn breaks!", "#ffd75e")
                self.end_night(None)
        elif ph == "dawn" and now >= self.phase_end:
            self.balance_bots()
            self.start_day()
        elif ph == "results" and now >= self.phase_end:
            self.phase, self.phase_end = "lobby", 0.0
            self.send_all(self.phase_msg())
        if not self.humans() and self.phase != "lobby":
            self.phase, self.phase_end = "lobby", 0.0
            self.balance_bots()
        self.hook("on_tick", DT, self.phase)
        self.flush(now)

    def player_info(self, p):
        return {"id": p.id, "name": p.name, "bot": p.bot, "color": p.color, "plot": p.plot, "cash": p.cash,
                "held": (p.held_gun() or {}).get("parts", {}), "heldName": (p.held_gun() or {}).get("name", ""),
                "slots": self.shelf_slots(p), "shelf": p.shelf[:self.shelf_slots(p)], "upgrades": p.upgrades,
                "kills": p.kills, "zkills": p.zkills, "nights": p.nights, "maxHp": p.max_hp}

    def flush(self, now):
        if self.dirty:
            self.dirty = False
            self.send_all({"t": "players", "list": [self.player_info(p) for p in self.players.values()]})
        for p in self.humans():
            if p.inv_dirty:
                p.inv_dirty = False
                self.send(p, {"t": "inv", "parts": p.parts, "guns": p.guns, "stock": p.stock, "held": p.held,
                              "effects": self.effects(p)})
        for p in self.players.values():
            p.inv_dirty = p.inv_dirty and not p.bot
        for ev in self.events:
            self.send_all(ev)
        self.events.clear()
        left = round(max(0, self.phase_end - now), 1)
        if self.phase in ("day", "night"):
            snap = [[p.id, round(p.s["x"], 3), round(p.s["y"], 3), round(p.s["z"], 3), round(p.h, 1), round(p.p, 1),
                     math.ceil(p.hp), 1 if p.alive else 0] for p in self.players.values()]
            extra = {}
            if self.phase == "day":
                extra["c"] = [[c["id"], round(c["x"], 2), round(c["y"], 2), round(c["h"]), 0 if c["state"] == "browse" else 1]
                              for c in self.customers.values()]
            else:
                extra["z"] = [[z.id, round(z.s["x"], 2), round(z.s["y"], 2), round(z.s["z"], 2), round(z.h), z.type_index,
                               math.ceil(z.hp), math.ceil(z.max_hp)] for z in self.zombies.values()]
            for p in self.humans():
                me = {"ammo": p.ammo, "reload": round(max(0, p.reload_until - now), 2), "ack": p.ack,
                      "spd": round(BASE_SPEED * p.stats["moveSpeed"] * p.speed_mul, 3),
                      "vz": round(p.s["vz"], 3), "gr": 1 if p.s["ground"] else 0}
                self.send(p, {"t": "s", "ph": self.phase, "p": snap, "me": me, "left": left, **extra})
        elif int(now * 2) != int((now - DT) * 2):
            self.send_all({"t": "s", "ph": self.phase, "p": [], "left": left})

    # ------------------------------------------------------------ net
    def _encode(self, msg):
        return (json.dumps(msg, separators=(",", ":")) + "\n").encode()

    def send(self, p, msg):
        if p.bot or not p.writer or p.writer.is_closing():
            return
        if p.writer.transport.get_write_buffer_size() > 4_000_000:
            log(f"{p.name} too slow - dropping")
            p.writer.close()
            return
        p.writer.write(self._encode(msg))

    def send_all(self, msg):
        data = self._encode(msg)
        for p in self.players.values():
            if not p.bot and p.writer and not p.writer.is_closing():
                p.writer.write(data)

    def chat_all(self, text, color="#ffd75e"):
        self.send_all({"t": "chat", "from": "", "msg": text, "color": color})

    def handle(self, p, m):
        t = m.get("t")
        if t == "in":
            h, pt = m.get("h", 0), m.get("pi", 0)
            if isinstance(h, (int, float)) and isinstance(pt, (int, float)) and math.isfinite(h) and math.isfinite(pt):
                p.h, p.p = float(h), max(-89.0, min(89.0, float(pt)))
            p.inp["fire"] = 1 if m.get("f") else 0
            p.inp["ads"] = 1 if m.get("ads") else 0
            if m.get("r"):
                p.inp["reload"] = 1
            for key, field in (("c", "clicks"), ("m", "melee")):
                v = m.get(key)
                if isinstance(v, int):
                    p.inp[field] = v
            seq = m.get("seq")
            if isinstance(seq, int) and len(p.moves) < 20:
                fwd = max(-1, min(1, int(m.get("mf", 0))))
                strafe = max(-1, min(1, int(m.get("ms", 0))))
                p.moves.append((seq, fwd, strafe, 1 if m.get("j") else 0, p.h))
        elif t == "act":
            self.act(p, m)
        elif t == "chat":
            text = str(m.get("msg", ""))[:200].strip()
            if not text:
                return
            if text.startswith("/"):
                self.run_command(p, text[1:])
            elif not self.hook("on_chat", p, text):
                self.send_all({"t": "chat", "from": p.name, "msg": text, "color": "#ffffff"})
                log(f"<{p.name}> {text}")

    def run_command(self, p, text):
        parts = text.split()
        if not parts:
            return
        cmd = self.commands.get(parts[0].lower())
        if not cmd:
            self.api.tell(p, f"Unknown command /{parts[0]} - try /help", "#ff7070")
            return
        try:
            cmd[0](self.api, p, parts[1:])
        except Exception as e:
            log(f"/{parts[0]} failed: {e!r}")

    def builtin_commands(self):
        api = self.api

        @api.command("help", "list commands")
        def _help(api, p, args):
            for n, (_, h) in sorted(self.commands.items()):
                api.tell(p, f"/{n}  {h}")

        @api.command("mods", "list installed mods")
        def _mods(api, p, args):
            for m in self.content["mods"]:
                api.tell(p, f"{m['name']} v{m['version']} - {m['description']}")

        @api.command("cash", "show everyone's cash")
        def _cash(api, p, args):
            for q in sorted(self.players.values(), key=lambda q: -q.cash):
                api.tell(p, f"{q.name}: ${q.cash}")

    def console(self, line):
        parts = line.strip().split()
        if not parts:
            return
        c, args = parts[0].lower(), parts[1:]
        if c == "help":
            print("say <msg> | list | kick <name> | skip | givecash <name> <n> | days <n> | minplayers <n> | bots on/off | reload | quit")
        elif c == "say":
            self.chat_all("[Server] " + " ".join(args))
        elif c == "list":
            for p in self.players.values():
                print(f"  #{p.id} {p.name} ${p.cash} guns={len(p.guns)} kills={p.kills}")
        elif c == "kick" and args:
            p = self.api.get_player(" ".join(args))
            if p and p.writer:
                self.send(p, {"t": "kicked", "reason": "Kicked by server"})
                p.writer.close()
        elif c == "skip":
            self.phase_end = time.monotonic()
        elif c == "givecash" and len(args) >= 2:
            p = self.api.get_player(args[0])
            if p:
                self.give_cash(p, int(args[1]), "Gift from the server")
        elif c == "days" and args:
            self.config["days"] = max(1, int(args[0]))
        elif c == "minplayers" and args:
            self.config["minPlayers"] = max(1, min(MAX_PLAYERS, int(args[0])))
            self.balance_bots()
        elif c == "bots" and args:
            self.config["bots"] = args[0].lower() in ("on", "1", "true", "yes")
            self.balance_bots()
        elif c == "reload":
            self.load()
            for p in self.humans():
                self.send(p, self.welcome(p))
            log("Mods reloaded")
        elif c in ("quit", "exit", "stop"):
            os._exit(0)
        else:
            print("Unknown command - type 'help'")


async def serve(root, config):
    game = Game(root, config)
    loop = asyncio.get_running_loop()

    async def on_client(reader, writer):
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        peer = writer.get_extra_info("peername")
        player = None
        try:
            hello = json.loads(await asyncio.wait_for(reader.readline(), 10))
            if hello.get("t") != "hello":
                return
            reject = None
            if hello.get("protocol") != PROTOCOL:
                reject = f"Version mismatch (server is {VERSION})"
            elif config["password"] and hello.get("password") != config["password"]:
                reject = "Wrong password"
            elif len(game.humans()) >= min(config["maxPlayers"], len(game.world["plots"])):
                reject = "Server full"
            if reject:
                writer.write(game._encode({"t": "kicked", "reason": reject}))
                await writer.drain()
                return
            name = "".join(ch for ch in str(hello.get("name", "Player")) if ch.isprintable())[:16].strip() or "Player"
            taken = {p.name for p in game.players.values()}
            base, n = name, 2
            while name in taken:
                name, n = f"{base}{n}", n + 1
            if len(game.players) >= len(game.world["plots"]):
                bots = [p for p in game.players.values() if p.bot]
                if bots:
                    game.remove_player(bots[-1])
            player = game.add_player(name, writer)
            game.send(player, game.welcome(player))
            if game.phase == "day":
                game.place_in_shop(player)
            elif game.phase == "night":
                player.alive = False
                game.api.tell(player, "A night is in progress - you'll join at dawn.")
            game.chat_all(f"{name} opened a shop in town")
            log(f"{name} joined from {peer[0] if peer else '?'}")
            game.hook("on_player_join", player)
            if game.phase == "lobby":
                game.balance_bots()
            if config["motd"]:
                game.api.tell(player, config["motd"], "#ffd75e")
            while True:
                line = await reader.readline()
                if not line or len(line) > 32768:
                    break
                try:
                    m = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(m, dict):
                    game.handle(player, m)
        except (asyncio.TimeoutError, ConnectionError, json.JSONDecodeError, OSError):
            pass
        finally:
            if player:
                game.remove_player(player)
                log(f"{player.name} disconnected")
                if game.phase == "lobby":
                    game.balance_bots()
            writer.close()

    server = await asyncio.start_server(on_client, "0.0.0.0", config["port"])
    log(f"LAST ARMORY server '{config['name']}' v{VERSION} listening on port {config['port']}")
    log("Type 'help' for console commands.")

    def read_console():
        while True:
            try:
                line = sys.stdin.readline()
            except Exception:
                return
            if not line:
                return
            loop.call_soon_threadsafe(game.console, line)

    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=read_console, daemon=True).start()

    nxt = time.monotonic()
    async with server:
        while True:
            try:
                game.tick()
            except Exception as e:
                log(f"TICK ERROR: {e!r}")
                import traceback
                traceback.print_exc()
            nxt += DT
            delay = nxt - time.monotonic()
            if delay < -0.5:
                nxt, delay = time.monotonic(), 0
            await asyncio.sleep(max(0, delay))


def load_config(root, path=None):
    path = path or os.path.join(root, "server_config.json")
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            cfg.update(json.load(f))
    else:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        log(f"Created default config: {path}")
    return cfg


def main(root, argv):
    import argparse
    ap = argparse.ArgumentParser(description="LAST ARMORY dedicated server")
    ap.add_argument("--config")
    ap.add_argument("--port", type=int)
    ap.add_argument("--name")
    ap.add_argument("--min-players", type=int)
    ap.add_argument("--no-bots", action="store_true")
    ap.add_argument("--days", type=int)
    ap.add_argument("--day-seconds", type=int)
    args = ap.parse_args(argv)
    cfg = load_config(root, args.config)
    if args.port: cfg["port"] = args.port
    if args.name: cfg["name"] = args.name
    if args.min_players: cfg["minPlayers"] = args.min_players
    if args.no_bots: cfg["bots"] = False
    if args.days: cfg["days"] = args.days
    if args.day_seconds: cfg["daySeconds"] = args.day_seconds
    try:
        asyncio.run(serve(root, cfg))
    except KeyboardInterrupt:
        log("Server stopped")
