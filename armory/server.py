"""LAST ARMORY dedicated server. Authoritative, 30 Hz, newline-delimited JSON over TCP (stdlib only).

One continuous game: a day/night clock runs for N days; the richest gunsmith wins.
Zones: "town" (always safe) and "outside" (zombies; PvP only while 2+ players are outside).
"""
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
from .sim import (BASE_SPEED, BODY_H, BODY_R, EYE_H, HEAD_R, HEAD_Z, LEG_Z, aim_vec, box_tuple, line_of_sight,
                  move_player, ray_box, ray_cylinder, ray_sphere, ray_world, spread_dir)
from .town import arena_boxes, build_town

TICK = 30
DT = 1.0 / TICK
BASE_SHELVES = 3
MAX_HP = 100.0
MAX_ARMOR = 50.0

DEFAULT_CONFIG = {
    "name": "Last Armory Server",
    "motd": "Build guns. Sell guns. Survive outside.",
    "port": 27030,
    "maxPlayers": 8,
    "password": "",
    "days": 5,
    "dayMinutes": 6,
    "nightMinutes": 3,
    "startCash": 400,
    "pvpMinPlayers": 2,
    "town": "",
    "outside": "",
    "disabledMods": [],
}

CUSTOMER_NAMES = ["Martha", "Old Joe", "Dina", "Sergei", "Pip", "Rosa", "Big Tom", "Yuki", "Abe", "Nell", "Hank",
                  "Iris", "Gus", "Mila", "Otto", "Faye", "Dutch", "Lena", "Moss", "Vik"]


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


class Body:
    def __init__(self):
        self.s = {"x": 0.0, "y": 0.0, "z": 0.0, "vz": 0.0, "ground": True}
        self.h = 0.0
        self.p = 0.0
        self.hp = MAX_HP
        self.alive = True

    @property
    def pos(self):
        return self.s["x"], self.s["y"], self.s["z"]


class Player(Body):
    def __init__(self, pid, name, writer=None):
        super().__init__()
        self.id, self.name, self.writer = pid, name, writer
        self.color = pid % 8
        self.plot = 0
        self.zone = "town"
        self.cash = 0
        self.parts = {}
        self.items = {}
        self.guns = []
        self.shelf = []
        self.upgrades = {}
        self.stock = []
        self.held = None
        self.stats = {}
        self.armor = 0.0
        self.hunger = 100.0
        self.energy = 100.0
        self.sleeping = False
        self.market_visit = False
        self.respawn_at = 0.0
        self.last_hurt = 0.0
        self.starve_t = 0.0
        self.clean = None
        self.kills = self.zkills = 0
        self.earned = 0
        self.ammo = 0
        self.reload_until = 0.0
        self.jammed = False
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

    def held_gun(self):
        return next((g for g in self.guns if g["id"] == self.held), None)


class Zombie(Body):
    def __init__(self, zid, ztype, index):
        super().__init__()
        self.id = zid
        self.type = ztype
        self.type_index = index
        self.hp = self.max_hp = float(ztype.get("hp", 60))
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
    def night(self): return self.game.is_night
    @property
    def time(self): return time.monotonic()

    def players(self, zone=None):
        return [p for p in self.game.players.values() if zone is None or p.zone == zone]

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

    def give_item(self, player, item_id, count=1):
        if item_id in self.game.content["items"]:
            player.items[item_id] = player.items.get(item_id, 0) + count
            player.inv_dirty = True

    def damage(self, player, amount, attacker=None):
        self.game.apply_damage(player, amount, attacker, "body")

    def heal(self, player, amount):
        if player.alive:
            player.hp = min(MAX_HP, player.hp + amount)

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
        self.next_loot = 1
        self.commands = {}
        self.events = []
        self.dirty = True
        self.phase = "lobby"
        self.phase_end = 0.0
        self.game_start = 0.0
        self.day = 0
        self.is_night = False
        self.customers = {}
        self.cust_t = 0.0
        self.zombies = {}
        self.zombie_t = 0.0
        self.empty_since = 0.0
        self.loot = {}
        self.loot_t = 0.0
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
        self.outside = c["arenas"].get(self.config.get("outside") or "") or next(iter(c["arenas"].values()))
        self.out_boxes = [box_tuple(b) for b in arena_boxes(self.outside)]
        self.start_kit = {p["slot"]: p["id"] for p in c["parts"].values() if p["start"]}
        log(f"Loaded {len(c['mods'])} mod(s): " + ", ".join(f"{m['name']} {m['version']}" for m in c["mods"]))
        log(f"{len(c['parts'])} parts, {len(c['items'])} items, {len(c['upgrades'])} upgrades, "
            f"town '{self.world['town'].get('name', '?')}' ({len(self.world['plots'])} shops, "
            f"{len(self.world['vendors'])} stalls), outside '{self.outside.get('name', '?')}'")
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
                "server": {"name": self.config["name"], "motd": self.config["motd"], "days": self.config["days"],
                           "dayMinutes": self.config["dayMinutes"], "nightMinutes": self.config["nightMinutes"],
                           "pvpMin": self.config["pvpMinPlayers"]},
                "content": client_payload(self.content), "town": self.world["town"]["id"],
                "shop": self.world["shop"]["id"], "towns": self.content["towns"], "shops": self.content["shops"],
                "outside": self.outside, "phase": self.phase_msg()}

    # ------------------------------------------------------------ helpers
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

    def make_gun(self, loadout, name=None, cond=None):
        g = {"id": self.next_gun, "name": (name or auto_name(loadout, self.content["parts"], random))[:24],
             "parts": dict(loadout), "value": gun_value(loadout, self.content["parts"]),
             "cond": round(random.uniform(0.3, 0.5) if cond is None else cond, 3)}
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

    def plot_of(self, p):
        return self.world["plots"][p.plot]

    def in_own_shop(self, p):
        c = self.plot_of(p)["center"]
        return p.zone == "town" and math.hypot(p.s["x"] - c[0], p.s["y"] - c[1]) < 14

    def near(self, p, point, dist):
        return math.hypot(p.s["x"] - point[0], p.s["y"] - point[1]) <= dist

    def outside_players(self):
        return [p for p in self.players.values() if p.zone == "outside" and p.alive]

    def pvp_on(self):
        return len(self.outside_players()) >= self.config["pvpMinPlayers"]

    # ------------------------------------------------------------ players
    def add_player(self, name, writer=None):
        p = Player(self.next_id, name, writer)
        self.next_id += 1
        used_c = {o.color for o in self.players.values()}
        p.color = next((c for c in range(8) if c not in used_c), p.id % 8)
        used_p = {o.plot for o in self.players.values()}
        p.plot = next((i for i in range(len(self.world["plots"])) if i not in used_p), 0)
        self.players[p.id] = p
        self.reset_player(p)
        if self.phase == "game":
            self.roll_stock(p)
        self.place_in_shop(p)
        self.dirty = True
        return p

    def reset_player(self, p):
        p.cash = self.config["startCash"]
        p.parts = {}
        for pid in self.start_kit.values():
            p.parts[pid] = p.parts.get(pid, 0) + 1
        p.items = {"canned_food": 2, "bandage": 1, "cleaning_kit": 1}
        p.items = {k: v for k, v in p.items.items() if k in self.content["items"]}
        starter = self.make_gun(self.start_kit, "Old Faithful", cond=0.8)
        p.guns = [starter]
        p.held = starter["id"]
        p.shelf = [None] * len(self.world["shop"]["shelves"])
        p.upgrades = {}
        p.kills = p.zkills = p.earned = 0
        p.hunger = p.energy = 100.0
        p.armor = 0.0
        p.inv_dirty = True
        self.restat(p)

    def restat(self, p):
        g = p.held_gun()
        p.stats = compute_stats(g["parts"] if g else self.start_kit, self.content["parts"])
        p.ammo = min(p.ammo, p.stats["magSize"]) if p.ammo else p.stats["magSize"]
        p.jammed = False
        self.dirty = True

    def remove_player(self, p):
        if self.players.pop(p.id, None):
            self.dirty = True
            for c in list(self.customers.values()):
                if c["plot"] == p.plot:
                    self.customer_leave(c, "Shop closed")
            self.hook("on_player_leave", p)
            self.chat_all(f"{p.name} left")

    def place_in_shop(self, p):
        sp = self.plot_of(p)["spawn"]
        p.zone = "town"
        p.s = {"x": sp[0], "y": sp[1], "z": 0.1, "vz": 0.0, "ground": True}
        p.h, p.p = sp[3], 0.0
        p.alive = True
        p.sleeping = False
        p.moves.clear()
        p.reload_until = 0.0
        p.ammo = p.stats.get("magSize", 10)
        self.send(p, {"t": "tp", "x": p.s["x"], "y": p.s["y"], "z": p.s["z"], "h": p.h, "zone": "town"})
        self.dirty = True

    def go_outside(self, p):
        sp = random.choice(self.outside.get("entry") or self.outside["spawns"])
        p.zone = "outside"
        p.s = {"x": float(sp[0]), "y": float(sp[1]), "z": float(sp[2]) + 0.1, "vz": 0.0, "ground": False}
        p.h, p.p = float(sp[3]) if len(sp) > 3 else 0.0, 0.0
        p.moves.clear()
        p.sleeping = False
        self.send(p, {"t": "tp", "x": p.s["x"], "y": p.s["y"], "z": p.s["z"], "h": p.h, "zone": "outside"})
        self.chat_all(f"{p.name} went outside" + ("  -  PvP is ON" if self.pvp_on() else ""), "#ff9d6b")
        self.hook("on_zone", p, "outside")
        self.dirty = True

    def return_to_town(self, p):
        gate = min(self.world["gates"], key=lambda g: abs(g[0] - self.world["size"][0] / 2))
        gx, gy = self.world["gates"][0]
        p.zone = "town"
        x = gx + (4 if gx < self.world["size"][0] / 2 else -4)
        p.s = {"x": float(x), "y": float(gy), "z": 0.1, "vz": 0.0, "ground": False}
        p.h = -90.0 if gx < self.world["size"][0] / 2 else 90.0
        p.moves.clear()
        self.send(p, {"t": "tp", "x": p.s["x"], "y": p.s["y"], "z": p.s["z"], "h": p.h, "zone": "town"})
        self.hook("on_zone", p, "town")
        self.dirty = True

    # ------------------------------------------------------------ phases
    def phase_msg(self):
        now = time.monotonic()
        m = {"t": "phase", "phase": self.phase, "day": self.day, "left": round(max(0, self.phase_end - now), 1)}
        if self.phase == "results":
            m["winner"] = self.winner_id
        return m

    def set_phase(self, ph, dur):
        self.phase = ph
        self.phase_end = time.monotonic() + dur
        self.send_all(self.phase_msg())
        self.hook("on_phase", ph)
        self.dirty = True

    def day_len(self):
        return (self.config["dayMinutes"] + self.config["nightMinutes"]) * 60.0

    def clock(self, now):
        t = max(0.0, now - self.game_start)
        L = self.day_len()
        day = 1 + int(t // L)
        frac = (t % L) / L
        night = frac >= self.config["dayMinutes"] * 60.0 / L
        return day, frac, night

    def start_game(self):
        self.day = 1
        self.is_night = False
        self.game_start = time.monotonic()
        self.customers.clear()
        self.zombies.clear()
        self.loot.clear()
        for p in self.players.values():
            self.reset_player(p)
            self.roll_stock(p)
            self.place_in_shop(p)
        self.set_phase("game", self.day_len() * self.config["days"])
        self.morning()
        log("Game started")

    def morning(self):
        self.hook("on_day_start", self.day)
        self.chat_all(f"Day {self.day} of {self.config['days']} - the shops are open!", "#ffd75e")
        for p in self.players.values():
            free = self.effects(p).get("armorMorning", 0)
            if free and p.armor < free:
                p.armor = min(MAX_ARMOR, free)
                self.send(p, {"t": "toast", "msg": f"Armor locker: +{int(free)} shields", "bad": 0})
        self.dirty = True

    def evening(self):
        self.hook("on_night_start", self.day)
        self.chat_all("Night falls. Customers go home - zombies come out. Get some sleep!", "#9ab0ff")
        for c in list(self.customers.values()):
            self.customer_leave(c, "Getting dark...")

    def end_game(self):
        best = max(self.players.values(), key=lambda p: p.cash, default=None)
        self.winner_id = best.id if best else 0
        if best:
            self.chat_all(f"{best.name} is the richest gunsmith with ${best.cash}!", "#ffb347")
        self.hook("on_match_end", best)
        self.set_phase("results", 15)

    # ------------------------------------------------------------ actions
    def act(self, p, m):
        a = m.get("a")
        if self.phase != "game" and a not in ("hold",):
            return self.fail(p, "Wait for the game to start")
        parts, items = self.content["parts"], self.content["items"]
        if p.sleeping and a not in ("wake",):
            return self.fail(p, "You're asleep (press E to wake up)")
        if a == "buy_part":
            i = m.get("i")
            if not isinstance(i, int) or not (0 <= i < len(p.stock)) or not p.stock[i]:
                return
            if not self.in_own_shop(p):
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
            g = self.make_gun(lo, str(m.get("name") or "").strip()[:24] or None)
            p.guns.append(g)
            if not p.held_gun():
                p.held = g["id"]
            self.events.append({"t": "crafted", "p": p.id, "gun": g})
            self.hook("on_craft", p, g)
        elif a == "disassemble":
            if not self.effects(p).get("disassemble"):
                return self.fail(p, "Upgrade your workbench to disassemble guns")
            g = next((g for g in p.guns if g["id"] == m.get("gid")), None)
            if not g:
                return
            p.guns.remove(g)
            for pid in g["parts"].values():
                p.parts[pid] = p.parts.get(pid, 0) + 1
            if p.held == g["id"]:
                p.held = p.guns[0]["id"] if p.guns else None
                self.restat(p)
        elif a == "shelve":
            slot, gid, price = m.get("slot"), m.get("gid"), m.get("price")
            if not isinstance(slot, int) or not (0 <= slot < self.shelf_slots(p)) or p.shelf[slot]:
                return self.fail(p, "That shelf isn't free")
            g = next((g for g in p.guns if g["id"] == gid), None)
            if not g or not isinstance(price, int) or not (1 <= price <= 999999):
                return
            if len(p.guns) <= 1:
                return self.fail(p, "Keep at least one gun to defend yourself!")
            p.guns.remove(g)
            if p.held == g["id"]:
                p.held = p.guns[0]["id"] if p.guns else None
                self.restat(p)
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
            for _ in range(int(levels[lvl].get("effects", {}).get("stock", 0))):
                p.stock.append(None)
        elif a == "buy_gun":
            o = self.players.get(m.get("owner"))
            slot = m.get("slot")
            if not o or o is p or not isinstance(slot, int) or not (0 <= slot < len(o.shelf)) or not o.shelf[slot]:
                return
            sx, sy, _, _ = self.world["plots"][o.plot]["shelves"][slot]
            if p.zone != "town" or not self.near(p, (sx, sy), 4.5):
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
        elif a == "buy_item":
            v = next((v for v in self.world["vendors"] if v["id"] == m.get("vendor")), None)
            it = items.get(m.get("item"))
            if not v or not it or it["id"] not in v["items"]:
                return
            if p.zone != "town" or not self.near(p, v["pos"], 4.0):
                return self.fail(p, "Walk up to the stall")
            if p.cash < it["price"]:
                return self.fail(p, "Not enough cash")
            p.cash -= it["price"]
            self.events.append({"t": "cash", "p": p.id, "n": -it["price"], "why": f"Bought {it['name']}"})
            if it["kind"] == "armor":
                if p.armor >= it["value"]:
                    p.cash += it["price"]
                    return self.fail(p, "You already have that much armor")
                p.armor = min(MAX_ARMOR, it["value"])
            else:
                p.items[it["id"]] = p.items.get(it["id"], 0) + 1
        elif a == "use_item":
            it = items.get(m.get("item"))
            if not it or p.items.get(it["id"], 0) <= 0 or not p.alive:
                return
            if not self.use_item(p, it):
                return
            p.items[it["id"]] -= 1
            if p.items[it["id"]] <= 0:
                del p.items[it["id"]]
        elif a == "sleep":
            bed = self.plot_of(p).get("bed")
            if not bed or not self.in_own_shop(p) or not self.near(p, bed, 3.0):
                return self.fail(p, "Sleep in the bed in your shop")
            if p.energy >= 95:
                return self.fail(p, "You're not tired")
            p.sleeping = True
            p.moves.clear()
            self.events.append({"t": "sleep", "p": p.id, "on": 1})
        elif a == "wake":
            if p.sleeping:
                p.sleeping = False
                self.events.append({"t": "sleep", "p": p.id, "on": 0})
        elif a == "go_out":
            if p.zone != "town" or not any(self.near(p, g, 4.5) for g in self.world["gates"]):
                return self.fail(p, "Go to the town gate")
            self.go_outside(p)
        elif a == "go_town":
            if p.zone != "outside" or not any(self.near(p, e, 4.0) for e in self.outside.get("exits", [])):
                return self.fail(p, "Find the road back to town")
            self.return_to_town(p)
        elif a == "loot":
            box = self.loot.get(m.get("id"))
            if not box or p.zone != "outside" or not self.near(p, box["pos"], 2.6):
                return
            del self.loot[box["id"]]
            self.events.append({"t": "loot_gone", "id": box["id"]})
            self.open_loot(p)
        elif a == "clean_start":
            g = next((g for g in p.guns if g["id"] == m.get("gid")), None)
            bench = self.plot_of(p).get("clean")
            if not g or not bench or not self.in_own_shop(p) or not self.near(p, bench, 3.5):
                return self.fail(p, "Use the cleaning bench in your shop")
            if p.items.get("cleaning_kit", 0) <= 0:
                return self.fail(p, "You need a cleaning kit (utility stall)")
            if g["cond"] >= 0.999:
                return self.fail(p, "That gun is already spotless")
            p.items["cleaning_kit"] -= 1
            if p.items["cleaning_kit"] <= 0:
                del p.items["cleaning_kit"]
            p.clean = {"gid": g["id"], "left": 40, "until": time.monotonic() + 60, "last": 0.0}
            self.send(p, {"t": "clean", "gid": g["id"], "left": 40, "cond": g["cond"]})
        elif a in ("scrub", "miss"):
            c = p.clean
            now = time.monotonic()
            if not c or now > c["until"]:
                p.clean = None
                return
            g = next((g for g in p.guns if g["id"] == c["gid"]), None)
            if not g:
                p.clean = None
                return
            if a == "scrub":
                if now - c["last"] < 0.08:   # rate limit: no auto-clickers
                    return
                c["last"] = now
                c["left"] -= 1
                g["cond"] = round(min(1.0, g["cond"] + 0.03), 3)
            else:
                c["left"] -= 3               # sloppy scrubbing wastes the kit
            if c["left"] <= 0 or g["cond"] >= 1.0:
                p.clean = None
            self.send(p, {"t": "clean", "gid": g["id"], "left": max(0, c["left"]) if p.clean else 0, "cond": g["cond"]})
            if g["id"] == p.held:
                self.dirty = True
        elif a == "clean_stop":
            p.clean = None
        else:
            return
        p.inv_dirty = True
        self.dirty = True

    def use_item(self, p, it):
        k, v = it["kind"], it["value"]
        if k == "food":
            if p.hunger >= 99:
                return self.fail(p, "You're full") and False
            p.hunger = min(100.0, p.hunger + v)
            p.energy = min(100.0, p.energy + it.get("energy", 0))
        elif k == "drink":
            p.energy = min(100.0, p.energy + v)
            p.hunger = min(100.0, p.hunger + it.get("hunger", 0))
        elif k == "heal":
            if p.hp >= MAX_HP:
                return self.fail(p, "You're at full health") and False
            p.hp = min(MAX_HP, p.hp + v)
        else:
            return False
        self.events.append({"t": "used", "p": p.id, "item": it["id"]})
        return True

    def open_loot(self, p):
        r = random.random()
        if r < 0.45:
            parts = [q for q in self.content["parts"].values() if not q["start"]]
            tier_cap = min(4, 1 + self.day // 2 + (1 if self.is_night else 0))
            pool = [q for q in parts if q["tier"] <= tier_cap] or parts
            part = random.choice(pool)
            p.parts[part["id"]] = p.parts.get(part["id"], 0) + 1
            self.send(p, {"t": "toast", "msg": f"Found: {part['name']}", "bad": 0})
        elif r < 0.8:
            self.give_cash(p, random.randint(40, 120) * (2 if self.is_night else 1), "Scavenged cash")
        else:
            its = [i for i in self.content["items"].values() if i["kind"] != "armor"]
            if its:
                it = random.choice(its)
                p.items[it["id"]] = p.items.get(it["id"], 0) + 1
                self.send(p, {"t": "toast", "msg": f"Found: {it['name']}", "bad": 0})
        p.inv_dirty = True

    def fail(self, p, text):
        self.send(p, {"t": "toast", "msg": text, "bad": 1})
        return None

    # ------------------------------------------------------------ customers (daytime only)
    def spawn_customer(self):
        shops = list(self.players.values())
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
        budget = random.uniform(250, 700) * (1 + 0.25 * (self.day - 1))
        if random.random() < 0.12:
            budget *= 2.5
        gate = random.choice(self.world["gates"])
        plot = self.world["plots"][shop.plot]
        c = {"id": self.next_cust, "name": random.choice(CUSTOMER_NAMES), "plot": shop.plot, "owner": shop.id,
             "x": float(gate[0]), "y": float(gate[1]), "h": 0.0, "pref": pref["id"] if pref else None,
             "budget": int(budget), "state": "walk", "t": 0.0,
             "wp": [plot["outside"][:2], plot["door"][:2], random.choice(plot["browse"])[:2]],
             "speed": random.uniform(3.0, 3.8), "look": random.randrange(8)}
        self.next_cust += 1
        self.hook("on_customer", c)
        self.customers[c["id"]] = c
        self.events.append({"t": "cust", "id": c["id"], "name": c["name"], "pref": c["pref"], "budget": c["budget"], "look": c["look"]})

    def customer_decide(self, c):
        """Customers buy something 80% of the time. A gun that matches what they want always sells,
        even above their stated budget (up to 1.6x)."""
        owner = self.players.get(c["owner"])
        if not owner:
            return self.customer_leave(c, "...")
        pref = self.content["customers"].get(c["pref"])
        wanted, other = [], []
        dirty = False
        for slot, item in enumerate(owner.shelf[:self.shelf_slots(owner)]):
            if not item:
                continue
            g = item["gun"]
            cond = g.get("cond", 1.0)
            if cond < 0.3:
                dirty = True
                continue
            st = compute_stats(g["parts"], self.content["parts"])
            match = 1.0
            if pref:
                v = max(1e-3, st.get(pref["stat"], 1))
                match = (pref["ref"] / v) if pref.get("lower") else (v / pref["ref"])
            worth = g["value"] * (0.75 + 0.45 * max(0.3, min(2.2, match))) * (0.45 + 0.55 * cond)
            entry = (worth - item["price"], slot, item, worth)
            if pref and match >= 1.0 and item["price"] <= c["budget"] * 1.6:
                wanted.append(entry)
            elif item["price"] <= c["budget"] and item["price"] <= worth * 1.5:
                other.append(entry)
        choice = None
        if wanted:
            choice = max(wanted, key=lambda e: e[0])
        elif other and random.random() < 0.8:
            choice = max(other, key=lambda e: e[0])
        if not choice:
            listed = any(owner.shelf[:self.shelf_slots(owner)])
            why = "Too dirty!" if dirty and not other else ("Too pricey!" if listed else "Nothing to buy!")
            return self.customer_leave(c, why)
        _, slot, item, _ = choice
        owner.shelf[slot] = None
        owner.inv_dirty = True
        over = item["price"] > c["budget"]
        self.give_cash(owner, item["price"], f"Sold {item['gun']['name']} to {c['name']}")
        self.events.append({"t": "sale", "seller": owner.id, "buyer": c["name"], "gun": item["gun"]["name"], "price": item["price"]})
        self.hook("on_sale", owner, c["name"], item["gun"], item["price"])
        self.customer_leave(c, "Had to have it!" if over else "Bought it!", True)

    def customer_leave(self, c, text, happy=False):
        plot = self.world["plots"][c["plot"]]
        gate = min(self.world["gates"], key=lambda g: math.hypot(g[0] - c["x"], g[1] - c["y"]))
        c["state"] = "leave"
        c["wp"] = [plot["door"][:2], plot["outside"][:2], list(gate)]
        self.events.append({"t": "cb", "id": c["id"], "text": text, "happy": 1 if happy else 0})

    def customers_tick(self, now):
        self.cust_t -= DT
        cap = 3 * max(1, len(self.players))
        if not self.is_night and self.cust_t <= 0 and len(self.customers) < cap:
            self.spawn_customer()
            self.cust_t = max(1.5, 7.0 - 0.5 * self.day) * random.uniform(0.6, 1.4) / max(1, len(self.players)) ** 0.5
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

    # ------------------------------------------------------------ combat
    def boxes_for(self, zone):
        return self.out_boxes if zone == "outside" else self.town_boxes

    def try_fire(self, p, now):
        st = p.stats
        if now < p.reload_until or now < p.next_shot:
            return
        if p.ammo <= 0 or p.jammed:
            if p.inp["reload"] or p.ammo <= 0:
                p.reload_until = now + st["reloadTime"] * (1.4 if p.jammed else 1.0)
                p.ammo = st["magSize"]
                p.jammed = False
            return
        wants = p.inp["fire"] if st["auto"] else p.inp["clicks"] > p.clicks_used
        if not wants:
            return
        p.clicks_used = p.inp["clicks"]
        p.next_shot = now + 1.0 / st["fireRate"]
        g = p.held_gun()
        cond = g.get("cond", 1.0) if g else 1.0
        if cond < 0.5 and random.random() < (0.5 - cond) * 0.3:
            p.jammed = True
            self.send(p, {"t": "toast", "msg": "JAMMED! Reload (R) - clean your gun", "bad": 1})
            return
        if g:
            g["cond"] = max(0.0, round(g["cond"] - 0.0015, 4))
        p.ammo -= 1
        cone = st["spread"] + p.bloom
        if p.moving or not p.s["ground"]:
            cone *= 1.5
        if p.inp["ads"]:
            cone *= 0.55
        if p.energy < 25:
            cone *= 1.4
        cone *= 1.0 + 0.3 * (1 - cond)
        p.bloom = min(12, p.bloom + st["recoil"])
        o = (p.s["x"], p.s["y"], p.s["z"] + EYE_H)
        boxes = self.boxes_for(p.zone)
        ends, hits = [], {}
        max_t = st["range"] * 1.6
        outside = p.zone == "outside"
        pvp = outside and self.pvp_on()
        for _ in range(st["pellets"]):
            d = spread_dir(p.h, p.p, cone)
            t, _w = ray_world(o, d, boxes, max_t)
            victim, part, tgt = None, "body", None
            if outside:
                cands = list(self.zombies.values()) + ([q for q in self.outside_players() if q is not p] if pvp else [])
                for q in cands:
                    if not q.alive:
                        continue
                    qx, qy, qz = q.pos
                    sc = q.type.get("scale", 1.0) if isinstance(q, Zombie) else 1.0
                    th = ray_sphere(o, d, (qx, qy, qz + HEAD_Z * sc), HEAD_R * sc)
                    tb = ray_cylinder(o, d, qx, qy, qz, qz + BODY_H * sc, BODY_R * sc)
                    for tt, kind in ((th, "head"), (tb, "body")):
                        if tt is not None and tt < t:
                            t, victim = tt, q
                            part = kind
                            if kind == "body" and o[2] + d[2] * tt - qz < LEG_Z * sc:
                                part = "legs"
            else:
                for tg in self.targets:
                    if tg["plot"] != p.plot:
                        continue
                    tt = ray_box(o, d, tg["box"])
                    if tt is not None and tt < t:
                        t, tgt = tt, tg
            end = (o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t)
            kind = 0 if victim is None else (2 if part == "head" else 1)
            if t >= max_t - 1e-3:
                kind = -1
            if tgt:
                kind = 3
            ends.append([round(end[0], 2), round(end[1], 2), round(end[2], 2), kind])
            fall = 1.0 if t <= st["range"] else max(0.0, 1 - (t - st["range"]) / (st["range"] * 0.6))
            mult = st["headshot"] if part == "head" else (0.85 if part == "legs" else 1.0)
            dmg = st["damage"] * fall * mult * p.damage_mul
            if victim:
                h = hits.setdefault(id(victim), [victim, 0.0, "legs"])
                h[1] += dmg
                if part == "head" or (part == "body" and h[2] == "legs"):
                    h[2] = part
            if tgt:
                self.events.append({"t": "thit", "p": p.id, "i": tgt["idx"], "plot": tgt["plot"], "n": round(dmg),
                                    "hd": 1 if part == "head" else 0})
            if outside and st["explosionRadius"] > 0 and kind != -1:
                self.explode(end, st["explosionRadius"], st["damage"] * 0.8 * p.damage_mul, p, skip=victim)
        self.events.append({"t": "shot", "p": p.id, "z": p.zone, "o": [round(o[0], 2), round(o[1], 2), round(o[2], 2)], "e": ends})
        for victim, dmg, part in hits.values():
            self.apply_damage(victim, dmg, p, part)

    def try_melee(self, p, now):
        if p.inp["melee"] <= p.melee_used or now < p.next_melee:
            return
        p.melee_used = p.inp["melee"]
        p.next_melee = now + 0.6
        self.events.append({"t": "melee", "p": p.id})
        if p.zone != "outside":
            return
        fx, fy, _ = aim_vec(p.h, 0)
        best, bd = None, 2.3
        cands = list(self.zombies.values()) + ([q for q in self.outside_players() if q is not p] if self.pvp_on() else [])
        for q in cands:
            dx, dy = q.s["x"] - p.s["x"], q.s["y"] - p.s["y"]
            d = math.hypot(dx, dy)
            if d < bd and (dx * fx + dy * fy) / max(1e-3, d) > 0.5 and abs(q.s["z"] - p.s["z"]) < 1.5:
                best, bd = q, d
        if best:
            self.apply_damage(best, p.stats.get("melee", 20) * p.damage_mul, p, "body")

    def explode(self, c, radius, damage, owner, skip=None):
        self.events.append({"t": "boom", "z": "outside", "x": round(c[0], 2), "y": round(c[1], 2), "zz": round(c[2], 2), "r": radius})
        targets = list(self.zombies.values()) + (self.outside_players() if self.pvp_on() else [owner] if owner else [])
        for q in targets:
            if not q or not q.alive or q is skip:
                continue
            qc = (q.s["x"], q.s["y"], q.s["z"] + 1.0)
            dist = math.dist(qc, c)
            if dist > radius + 0.5 or not line_of_sight(c, qc, self.out_boxes):
                continue
            amt = damage * (1 - 0.7 * min(1, dist / radius))
            if q is owner:
                amt *= 0.5
            self.apply_damage(q, amt, owner, "body")

    def apply_damage(self, victim, amount, attacker, part="body"):
        if not victim.alive:
            return
        if isinstance(victim, Zombie):
            victim.hp -= amount
            self.events.append({"t": "dmg", "v": -victim.id, "a": attacker.id if isinstance(attacker, Player) else 0,
                                "n": round(amount), "hd": 1 if part == "head" else 0})
            if victim.hp <= 0:
                victim.alive = False
                self.zombies.pop(victim.id, None)
                if isinstance(attacker, Player):
                    attacker.zkills += 1
                    reward = victim.type.get("reward", 15) * (1.5 if self.is_night else 1.0)
                    self.give_cash(attacker, reward, f"{victim.type.get('name', 'Zombie')} killed")
                    self.hook("on_zombie_kill", victim, attacker)
                self.events.append({"t": "zdead", "id": victim.id})
            return
        if victim.zone != "outside" and attacker is not None:
            return   # the town is a safe zone
        ev = {"victim": victim, "attacker": attacker, "amount": amount, "part": part, "head": part == "head", "cancel": False}
        self.hook("on_damage", ev)
        if ev["cancel"]:
            return
        amount = max(0.0, ev["amount"])
        absorbed = min(victim.armor, amount)       # Valorant-style shields soak damage first
        victim.armor -= absorbed
        victim.hp -= amount - absorbed
        victim.last_hurt = time.monotonic()
        victim.sleeping = False
        if isinstance(attacker, Player) and attacker is not victim:
            victim.last_hit_by = attacker.id
        self.events.append({"t": "dmg", "v": victim.id, "a": attacker.id if isinstance(attacker, Player) else 0,
                            "n": round(amount), "hd": 1 if part == "head" else 0, "ar": round(absorbed)})
        if victim.hp <= 0:
            self.kill_player(victim, attacker)

    def kill_player(self, victim, attacker):
        victim.hp = 0
        victim.alive = False
        victim.armor = 0.0
        victim.respawn_at = time.monotonic() + 6
        killer = attacker if isinstance(attacker, Player) and attacker is not victim else self.players.get(victim.last_hit_by)
        gun = ""
        if killer and killer.zone == "outside":
            killer.kills += 1
            loot = int(min(victim.cash * 0.25, 500))
            if loot > 0:
                victim.cash -= loot
                self.events.append({"t": "cash", "p": victim.id, "n": -loot, "why": f"Looted by {killer.name}"})
                self.give_cash(killer, loot, f"Looted {victim.name}")
            g = killer.held_gun()
            gun = g["name"] if g else ""
        elif isinstance(attacker, Zombie):
            bill = int(min(victim.cash * 0.1, 200))
            if bill:
                victim.cash -= bill
                self.events.append({"t": "cash", "p": victim.id, "n": -bill, "why": "Rescue fee"})
        self.events.append({"t": "kill", "k": killer.id if killer else 0, "v": victim.id, "gun": gun,
                            "z": 1 if isinstance(attacker, Zombie) else 0, "starved": 1 if attacker is None else 0})
        self.dirty = True
        self.hook("on_kill", victim, killer)

    # ------------------------------------------------------------ outside: zombies + loot
    def spawn_zombie(self, type_id=None, x=None, y=None):
        types = [z for z in self.content["zombies"].values() if z.get("minDay", 1) <= max(1, self.day)] \
            or list(self.content["zombies"].values())
        if not types:
            return None
        zt = self.content["zombies"].get(type_id) if type_id else random.choices(types, weights=[z.get("weight", 10) for z in types])[0]
        index = list(self.content["zombies"]).index(zt["id"])
        z = Zombie(self.next_zombie, zt, index)
        self.next_zombie += 1
        if x is None:
            pts = self.outside.get("zspawns") or self.outside["spawns"]
            far = [q for q in pts if all(math.hypot(q[0] - p.s["x"], q[1] - p.s["y"]) > 14 for p in self.outside_players())] or pts
            sp = random.choice(far)
            x, y = sp[0] + random.uniform(-1.5, 1.5), sp[1] + random.uniform(-1.5, 1.5)
        z.s.update(x=float(x), y=float(y), z=0.0)
        mul = (1 + 0.15 * (self.day - 1)) * (1.35 if self.is_night else 1.0)
        z.hp = z.max_hp = zt.get("hp", 60) * mul
        self.zombies[z.id] = z
        return z

    def outside_tick(self, now):
        outs = self.outside_players()
        if not outs:
            if self.zombies and now - self.empty_since > 30:
                self.zombies.clear()
            return
        self.empty_since = now
        cap = (6 + 3 * len(outs) + self.day) * (2 if self.is_night else 1)
        self.zombie_t -= DT
        if self.zombie_t <= 0 and len(self.zombies) < min(45, cap):
            for _ in range(random.randint(1, 2 + (2 if self.is_night else 0))):
                self.spawn_zombie()
            self.zombie_t = random.uniform(2.5, 5.0) / (1.6 if self.is_night else 1.0)
        self.loot_t -= DT
        spots = self.outside.get("loot") or []
        if spots and self.loot_t <= 0 and len(self.loot) < max(3, len(spots) // 2):
            taken = {tuple(b["pos"][:2]) for b in self.loot.values()}
            free = [s for s in spots if tuple(s[:2]) not in taken]
            if free:
                s = random.choice(free)
                b = {"id": self.next_loot, "pos": [s[0], s[1], s[2] if len(s) > 2 else 0]}
                self.next_loot += 1
                self.loot[b["id"]] = b
            self.loot_t = random.uniform(15, 30)
        size = self.outside["size"]
        for z in list(self.zombies.values()):
            tgt = min(outs, key=lambda p: math.hypot(p.s["x"] - z.s["x"], p.s["y"] - z.s["y"]))
            dx, dy = tgt.s["x"] - z.s["x"], tgt.s["y"] - z.s["y"]
            d = math.hypot(dx, dy)
            z.h = math.degrees(math.atan2(-dx, dy))
            if d < 1.25 and abs(tgt.s["z"] - z.s["z"]) < 1.6:
                if now >= z.next_hit:
                    z.next_hit = now + 1.0
                    self.apply_damage(tgt, z.type.get("damage", 12) * (1.3 if self.is_night else 1.0), z, "body")
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
            move_player(z.s, 1, 0, jump, z.h, z.type.get("speed", 3.0) * (1.15 if self.is_night else 1.0), DT, self.out_boxes, size)

    # ------------------------------------------------------------ survival + movement
    def survival_tick(self, p, now):
        L = self.day_len()
        p.hunger = max(0.0, p.hunger - 100.0 / (1.6 * L) * DT)
        if p.sleeping:
            p.energy = min(100.0, p.energy + 100.0 / 14.0 * DT)
            if p.energy >= 100.0:
                p.sleeping = False
                self.events.append({"t": "sleep", "p": p.id, "on": 0})
                self.send(p, {"t": "toast", "msg": "Well rested!", "bad": 0})
        else:
            p.energy = max(0.0, p.energy - 100.0 / (1.0 * L) * DT)
        if p.hunger <= 0:
            p.starve_t += DT
            if p.starve_t >= 2.0:
                p.starve_t = 0.0
                p.hp -= 2
                if p.hp <= 0:
                    self.kill_player(p, None)
        elif p.hunger > 50 and now - p.last_hurt > 8 and p.hp < MAX_HP:
            p.hp = min(MAX_HP, p.hp + 0.4 * DT)
        if p.zone == "town" and self.near(p, self.world["plaza"], 7.0) and not p.market_visit:
            p.market_visit = True
        if p.market_visit and self.in_own_shop(p):
            p.market_visit = False
            self.roll_stock(p)
            self.send(p, {"t": "toast", "msg": "New parts arrived at your supplier!", "bad": 0})

    def move_tick(self, now):
        for p in list(self.players.values()):
            if not p.alive:
                if now >= p.respawn_at:
                    p.hp = MAX_HP
                    p.hunger = max(p.hunger, 40.0)
                    self.place_in_shop(p)
                continue
            self.survival_tick(p, now)
            boxes = self.boxes_for(p.zone)
            size = self.outside["size"] if p.zone == "outside" else self.world["size"]
            tired = 0.6 if p.energy <= 0 else (0.8 if p.energy < 25 else 1.0)
            speed = BASE_SPEED * p.stats["moveSpeed"] * p.speed_mul * tired
            if len(p.moves) > 4:
                del p.moves[:len(p.moves) - 2]
            if p.moves:
                seq, fwd, strafe, jump, h = p.moves.pop(0)
                p.ack = seq
                if p.sleeping:
                    fwd = strafe = jump = 0
                move_player(p.s, fwd, strafe, jump, h, speed, DT, boxes, size)
                p.moving = bool(fwd or strafe)
            else:
                move_player(p.s, 0, 0, 0, p.h, speed, DT, boxes, size)
                p.moving = False
            p.bloom = max(0.0, p.bloom - 8 * DT)
            if p.reload_until and now >= p.reload_until:
                p.reload_until = 0.0
            if p.inp["reload"] and not p.reload_until and (p.ammo < p.stats["magSize"] or p.jammed):
                p.reload_until = now + p.stats["reloadTime"] * (1.4 if p.jammed else 1.0)
                p.ammo = p.stats["magSize"]
                p.jammed = False
            p.inp["reload"] = 0
            if not p.sleeping:
                self.try_fire(p, now)
                self.try_melee(p, now)

    def tick(self):
        now = time.monotonic()
        ph = self.phase
        if ph == "lobby":
            if self.players:
                if not self.phase_end:
                    self.set_phase("lobby", 8)
                elif now >= self.phase_end:
                    self.start_game()
            else:
                self.phase_end = 0.0
        elif ph == "game":
            day, frac, night = self.clock(now)
            if day > self.config["days"]:
                self.end_game()
            else:
                if day != self.day:
                    self.day = day
                    self.is_night = False
                    self.morning()
                if night != self.is_night:
                    self.is_night = night
                    if night:
                        self.evening()
                self.move_tick(now)
                self.customers_tick(now)
                self.outside_tick(now)
        elif ph == "results" and now >= self.phase_end:
            self.phase, self.phase_end = "lobby", 0.0
            self.send_all(self.phase_msg())
        if not self.players and self.phase != "lobby":
            self.phase, self.phase_end = "lobby", 0.0
        self.hook("on_tick", DT, self.phase)
        self.flush(now)

    def player_info(self, p):
        g = p.held_gun() or {}
        return {"id": p.id, "name": p.name, "color": p.color, "plot": p.plot, "cash": p.cash, "zone": p.zone,
                "held": g.get("parts", {}), "heldName": g.get("name", ""), "heldCond": g.get("cond", 1.0),
                "slots": self.shelf_slots(p), "shelf": p.shelf[:self.shelf_slots(p)], "upgrades": p.upgrades,
                "kills": p.kills, "zkills": p.zkills, "sleeping": p.sleeping}

    def flush(self, now):
        if self.dirty:
            self.dirty = False
            self.send_all({"t": "players", "list": [self.player_info(p) for p in self.players.values()]})
        for p in self.players.values():
            if p.inv_dirty:
                p.inv_dirty = False
                self.send(p, {"t": "inv", "parts": p.parts, "items": p.items, "guns": p.guns, "stock": p.stock,
                              "held": p.held, "effects": self.effects(p)})
        for ev in self.events:
            zone = ev.get("z")
            if ev["t"] in ("shot", "boom") and zone:
                for p in self.players.values():
                    if p.zone == zone:
                        self.send(p, ev)
            else:
                self.send_all(ev)
        self.events.clear()
        left = round(max(0, self.phase_end - now), 1)
        if self.phase != "game":
            if int(now * 2) != int((now - DT) * 2):
                self.send_all({"t": "s", "ph": self.phase, "p": [], "left": left})
            return
        day, frac, night = self.clock(now)
        rows = {"town": [], "outside": []}
        for p in self.players.values():
            rows[p.zone].append([p.id, round(p.s["x"], 3), round(p.s["y"], 3), round(p.s["z"], 3), round(p.h, 1), round(p.p, 1),
                                 math.ceil(p.hp), 1 if p.alive else 0])
        cust = [[c["id"], round(c["x"], 2), round(c["y"], 2), round(c["h"]), 0 if c["state"] == "browse" else 1]
                for c in self.customers.values()]
        zomb = [[z.id, round(z.s["x"], 2), round(z.s["y"], 2), round(z.s["z"], 2), round(z.h), z.type_index,
                 math.ceil(z.hp), math.ceil(z.max_hp)] for z in self.zombies.values()]
        loot = [[b["id"]] + b["pos"] for b in self.loot.values()]
        pvp = self.pvp_on()
        for p in self.players.values():
            me = {"ammo": p.ammo, "reload": round(max(0, p.reload_until - now), 2), "ack": p.ack,
                  "spd": round(BASE_SPEED * p.stats["moveSpeed"] * p.speed_mul * (0.6 if p.energy <= 0 else (0.8 if p.energy < 25 else 1.0)), 3),
                  "vz": round(p.s["vz"], 3), "gr": 1 if p.s["ground"] else 0, "hp": math.ceil(p.hp),
                  "ar": math.ceil(p.armor), "hu": round(p.hunger, 1), "en": round(p.energy, 1),
                  "sl": 1 if p.sleeping else 0, "jam": 1 if p.jammed else 0, "zone": p.zone,
                  "resp": round(max(0, p.respawn_at - now), 1) if not p.alive else 0}
            msg = {"t": "s", "ph": "game", "zone": p.zone, "p": rows[p.zone], "me": me, "left": left,
                   "day": day, "tod": round(frac, 4), "night": 1 if night else 0, "pvp": 1 if pvp else 0,
                   "out": len(self.outside_players())}
            if p.zone == "town":
                msg["c"] = cust
            else:
                msg["z"] = zomb
                msg["l"] = loot
            self.send(p, msg)

    # ------------------------------------------------------------ net
    def _encode(self, msg):
        return (json.dumps(msg, separators=(",", ":")) + "\n").encode()

    def send(self, p, msg):
        if not p.writer or p.writer.is_closing():
            return
        if p.writer.transport.get_write_buffer_size() > 4_000_000:
            log(f"{p.name} too slow - dropping")
            p.writer.close()
            return
        p.writer.write(self._encode(msg))

    def send_all(self, msg):
        data = self._encode(msg)
        for p in self.players.values():
            if p.writer and not p.writer.is_closing():
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
            print("say <msg> | list | kick <name> | givecash <name> <n> | days <n> | skipday | reload | quit")
        elif c == "say":
            self.chat_all("[Server] " + " ".join(args))
        elif c == "list":
            for p in self.players.values():
                print(f"  #{p.id} {p.name} ${p.cash} zone={p.zone} guns={len(p.guns)} kills={p.kills}")
        elif c == "kick" and args:
            p = self.api.get_player(" ".join(args))
            if p and p.writer:
                self.send(p, {"t": "kicked", "reason": "Kicked by server"})
                p.writer.close()
        elif c == "givecash" and len(args) >= 2:
            p = self.api.get_player(args[0])
            if p:
                self.give_cash(p, int(args[1]), "Gift from the server")
        elif c == "days" and args:
            self.config["days"] = max(1, int(args[0]))
        elif c == "skipday":
            self.game_start -= self.day_len()
        elif c == "reload":
            self.load()
            for p in self.players.values():
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
            elif len(game.players) >= min(config["maxPlayers"], len(game.world["plots"])):
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
            player = game.add_player(name, writer)
            game.send(player, game.welcome(player))
            game.place_in_shop(player)
            game.chat_all(f"{name} opened a shop in town")
            log(f"{name} joined from {peer[0] if peer else '?'}")
            game.hook("on_player_join", player)
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
    ap.add_argument("--days", type=int)
    ap.add_argument("--day-minutes", type=float)
    ap.add_argument("--night-minutes", type=float)
    args, _unknown = ap.parse_known_args(argv)
    cfg = load_config(root, args.config)
    if args.port: cfg["port"] = args.port
    if args.name: cfg["name"] = args.name
    if args.days: cfg["days"] = args.days
    if args.day_minutes: cfg["dayMinutes"] = args.day_minutes
    if args.night_minutes: cfg["nightMinutes"] = args.night_minutes
    try:
        asyncio.run(serve(root, cfg))
    except KeyboardInterrupt:
        log("Server stopped")
