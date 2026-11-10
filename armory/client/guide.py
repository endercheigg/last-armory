"""The "NEXT" box: walks a new player through their first day, then keeps giving timely tips.

Everything here is read from what the client already knows (inventory, shelf, vitals), so it needs no server
support and never blocks anything - it only suggests, and points a waypoint marker at the place to go.
"""
import math


class Guide:
    def __init__(self, m):
        self.m = m
        self.done = set()
        self._target = None
        self.finished_at = None

    def mark(self, what):
        self.done.add(what)

    def target(self):
        """(world pos, label, is_urgent) for the waypoint marker, or None."""
        return self._target

    def _plot(self):
        m = self.m
        plots = m.town["plots"]
        return plots[m.infos.get(m.me, {}).get("plot", 0) % len(plots)]

    def update(self):
        """Returns (heading, text) for the HUD box and sets the marker target."""
        m = self.m
        self._target = None
        if m.phase != "game" or m.me not in m.infos:
            return "", ""
        inv, me = m.inv, m.me_state
        pl = self._plot()
        town = m.zone != "outside"
        items = inv.get("items", {})
        content_items = m.content.get("items", {})
        has = lambda kind: any(n > 0 and content_items.get(i, {}).get("kind") == kind for i, n in items.items())
        pos = getattr(m.view, "render_pos", None)

        def at(key, label, urgent=False, z=1.6):
            if town and pl.get(key):
                q = pl[key]
                self._target = ((q[0], q[1], z), label, urgent)

        # ---- sticky progress
        if any(o and o.get("sold") for o in inv.get("stock", [])):
            self.done.add("bought")
        if len(inv.get("guns", [])) >= 2:
            self.done.add("built")
        if any(m.infos[m.me].get("shelf", [])):
            self.done.add("shelved")
        if not town:
            self.done.add("outside")
        if town and pos is not None:
            pz = m.town.get("plaza", [0, 0])
            if math.hypot(pos.x - pz[0], pos.y - pz[1]) < 9:
                self.done.add("plaza")

        # ---- urgent tips beat the walkthrough
        hp, hunger, energy = me.get("hp", 100), me.get("hu", 100), me.get("en", 100)
        if hp < 40 and has("heal"):
            return "LOW HEALTH", "Press H to use a bandage or medkit."
        if hunger < 20:
            if has("food"):
                return "HUNGRY", "Press G to eat something."
            return "HUNGRY", "You're out of food. Buy some at Ma's Diner in the town plaza before you starve."
        if energy < 20 and not me.get("sl"):
            at("bed", "BED", True, 1.0)
            return "EXHAUSTED", "You're slow and tired. Sleep in the bed at the back of your shop (E)." if town else \
                "You're slow and tired. Head back to town and sleep in your bed."
        info = m.infos[m.me]
        if info.get("held") and info.get("heldCond", 1) < 0.4 and "built" in self.done:
            at("clean", "CLEANING BENCH", True, 1.2)
            return "FILTHY GUN", "Your gun will jam. Clean it at the cleaning bench in your shop (needs a cleaning kit from Ironside Supply)."

        if not town:
            return "", ""          # out in the wasteland: no shop lessons, just stay alive

        # ---- first-day walkthrough
        if "bought" not in self.done and "built" not in self.done:
            at("terminal", "SUPPLIER")
            return "NEXT  (1/6)", "Buy a receiver, a barrel and a magazine at the SUPPLIER: the computer desk at the back of your shop."
        if "built" not in self.done:
            at("workbench", "WORKBENCH")
            return "NEXT  (2/6)", "Build a gun at the WORKBENCH: place a receiver, add a barrel and magazine, then tighten every screw."
        if "shelved" not in self.done and "sold" not in self.done:
            if town and pl.get("shelves"):
                q = pl["shelves"][0]
                self._target = ((q[0], q[1], 1.5), "SHELF", False)
            return "NEXT  (3/6)", "Put your new gun on a SHELF by the door and set a price. Customers pay more for guns that match what they want."
        if "sold" not in self.done and "job" not in self.done:
            if m.jobs:
                at("service", "CLIENT WAITING")
            return "NEXT  (4/6)", "Wait for a sale. Meanwhile, clients queue at your SERVICE WINDOW (left of the door) to have guns cleaned for cash."
        if "plaza" not in self.done:
            if town:
                pz = m.town.get("plaza", [0, 0])
                self._target = ((pz[0], pz[1], 2.5), "PLAZA", False)
            return "NEXT  (5/6)", "Visit the town PLAZA: food, medkits, armor, and the COLLECTOR's big-money special orders. Your supplier restocks when you get back."
        if "outside" not in self.done:
            if town and pos is not None:
                g = min(m.town.get("gates", [[0, 0]]), key=lambda g: math.hypot(g[0] - pos.x, g[1] - pos.y))
                self._target = ((g[0], g[1], 2.0), "TOWN GATE", False)
            return "NEXT  (6/6)", "Take a good gun through a TOWN GATE: zombies pay cash, crates hold parts. PvP switches on when 2+ players are out."

        # ---- after the walkthrough: light reminders
        if town and m.jobs and not m.panel:
            at("service", "CLIENT WAITING")
            return "TIP", f"{m.jobs[0]['name']} is waiting at your service window (${m.jobs[0]['pay']})."
        if m.blood and town:
            return "BLOOD MOON", "Zombie kills pay double tonight, and the Butcher is out there with a crate of rare parts."
        if m.is_night and town and energy < 60 and not me.get("sl"):
            at("bed", "BED", False, 1.0)
            return "TIP", "No customers at night. Sleep to refill your energy, or go hunting outside."
        return "", ""
