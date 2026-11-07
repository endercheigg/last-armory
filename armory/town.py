"""Builds the town (shared by server and client) from a town JSON + a shop template JSON.

Shop templates use local coordinates: x across the shop, y from the front door (y=0) inward.
Each plot places a copy of the shop at an origin with a rotation (0/90/180/270 degrees).
"""
import math


def _rot(rot):
    r = math.radians(rot)
    return round(math.cos(r)), round(math.sin(r))


def to_world(plot, lx, ly):
    c, s = _rot(plot["rot"])
    return plot["x"] + c * lx - s * ly, plot["y"] + s * lx + c * ly


def box_to_world(plot, b):
    x0, y0 = to_world(plot, b["x"], b["y"])
    x1, y1 = to_world(plot, b["x"] + b["w"], b["y"] + b["d"])
    return {"x": min(x0, x1), "y": min(y0, y1), "z": b.get("z", 0), "w": abs(x1 - x0), "d": abs(y1 - y0),
            "h": b["h"], "color": b.get("color", "#777777")}


def point(plot, p, z=0.0):
    x, y = to_world(plot, p[0], p[1])
    return [x, y, p[2] if len(p) > 2 else z]


def build_town(content, town_id=None, shop_id=None):
    towns = content["towns"]
    town = towns.get(town_id) or next(iter(towns.values()))
    shops = content["shops"]
    shop = shops.get(shop_id or town.get("shop")) or next(iter(shops.values()))
    boxes = [dict(b) for b in town.get("boxes", [])]
    plots = []
    targets = []
    objects = []
    for i, pl in enumerate(town["plots"]):
        p = {"index": i, "x": pl["x"], "y": pl["y"], "rot": pl.get("rot", 0)}
        for b in shop.get("boxes", []):
            boxes.append(box_to_world(p, b))
        sw, sd = shop.get("size", [12, 20])
        p["center"] = point(p, (sw / 2, sd / 2))
        p["door"] = point(p, shop["door"])
        p["outside"] = point(p, (shop["door"][0], shop["door"][1] - 3))
        p["browse"] = [point(p, b) for b in shop.get("browse", [shop["door"]])]
        sx, sy = to_world(p, shop["spawn"][0], shop["spawn"][1])
        p["spawn"] = [sx, sy, 0.0, (shop["spawn"][2] if len(shop["spawn"]) > 2 else 0) + p["rot"]]
        p["shelves"] = []
        for j, sh in enumerate(shop["shelves"]):
            x, y = to_world(p, sh[0], sh[1])
            p["shelves"].append([x, y, sh[2] if len(sh) > 2 else 1.2, (sh[3] if len(sh) > 3 else 0) + p["rot"]])
            objects.append({"kind": "shelf", "plot": i, "slot": j, "pos": [x, y, sh[2] if len(sh) > 2 else 1.2]})
        for kind in ("workbench", "terminal", "board"):
            q = point(p, shop[kind], 1.0)
            p[kind] = q
            objects.append({"kind": kind, "plot": i, "pos": q})
        for j, t in enumerate(shop.get("targets", [])):
            x, y = to_world(p, t[0], t[1])
            tb = (x - 0.4, y - 0.4, 0.0, 0.8, 0.8, 1.9)
            targets.append({"plot": i, "idx": j, "box": tb, "pos": [x, y, 1.2]})
        p["decor"] = [[box_to_world(p, b) for b in level] for level in shop.get("decor", [])]
        p["sign"] = [[box_to_world(p, b) for b in level] for level in shop.get("sign", [])]
        p["awning"] = [box_to_world(p, b) for b in shop.get("awning", [])]
        p["sign_text"] = point(p, shop.get("signText", [sw / 2, -0.4, 3.6]), 3.6)
        p["sign_rot"] = p["rot"]
        plots.append(p)
    return {"town": town, "shop": shop, "size": town["size"], "boxes": boxes, "plots": plots,
            "targets": targets, "objects": objects, "gates": town.get("gates", [[2, town["size"][1] / 2]]),
            "plaza": town.get("plaza", [town["size"][0] / 2, town["size"][1] / 2])}
