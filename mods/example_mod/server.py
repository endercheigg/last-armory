"""Example gameplay script - runs on the server only; players install nothing.

Shows: reading a custom upgrade effect ("zombieBounty"), reacting to sales, editing customers, chat commands.
Every hook is optional.
"""
import random


def on_load(api):
    api.log("Example mod loaded")

    @api.command("richest", "who is winning?")
    def richest(api, player, args):
        top = max(api.players(), key=lambda p: p.cash)
        api.tell(player, f"{top.name} leads with ${top.cash}")

    @api.command("tip", "a random gunsmith tip")
    def tip(api, player, args):
        api.tell(player, random.choice([
            "Customers pay up to ~1.3x what a gun is worth if it matches what they want.",
            "Walk into a rival's shop and buy their best gun before night falls!",
            "A bayonet (F) saves ammo against zombies.",
        ]))


def on_day_start(api, day):
    if day == 3:
        api.broadcast("Word is a rich collector is in town today. Price high!", "#ff9d3b")


def on_customer(api, customer):
    # customers are plain dicts: name, pref, budget, tol ...
    if api.day == 3 and random.random() < 0.3:
        customer["budget"] = int(customer["budget"] * 3)
        customer["name"] = "Rich " + customer["name"]


def on_zombie_kill(api, zombie, killer):
    bonus = api.game.effects(killer).get("zombieBounty", 0)
    if bonus:
        api.give_cash(killer, bonus, "Bounty board")


def on_sale(api, seller, buyer_name, gun, price):
    if price >= 500:
        api.broadcast(f"{seller.name} just sold {gun['name']} for ${price}!", "#ffd75e")
