"""Shared simulation: first-person movement/collision and ray casts (server + client prediction).
Coordinates: Z up, Y forward (Panda3D style). Headings in degrees: 0 = +Y, 90 = -X.
"""
import math
import random

# ---- arena player
GRAVITY = 22.0
JUMP_V = 8.0
PLAYER_R = 0.38
PLAYER_H = 1.92      # realistic adult height (taller characters)
EYE_H = 1.70
BASE_SPEED = 6.5
STEP_H = 0.55
BODY_R = 0.34
BODY_H = 1.56
HEAD_Z = 1.74
HEAD_R = 0.15        # small, Valorant-like head hitbox
LEG_Z = 0.9          # hits below this height count as legs (x0.85)



def box_tuple(b):
    return (b["x"], b["y"], b.get("z", 0), b["w"], b["d"], b["h"])


def _overlaps(x, y, z, b):
    bx, by, bz, bw, bd, bh = b
    return (bx - PLAYER_R < x < bx + bw + PLAYER_R and by - PLAYER_R < y < by + bd + PLAYER_R
            and bz - PLAYER_H < z < bz + bh)


def _free(x, y, z, boxes):
    return not any(_overlaps(x, y, z, b) for b in boxes)


def forward_vec(h):
    r = math.radians(h)
    return -math.sin(r), math.cos(r)


def aim_vec(h, p):
    r, q = math.radians(h), math.radians(p)
    return -math.sin(r) * math.cos(q), math.cos(r) * math.cos(q), math.sin(q)


def move_player(s, fwd, strafe, jump, heading, speed, dt, boxes, size):
    """s: dict with x, y, z, vz, ground. Mutates and returns s."""
    fx, fy = forward_vec(heading)
    rx, ry = fy, -fx
    wx, wy = fx * fwd + rx * strafe, fy * fwd + ry * strafe
    l = math.hypot(wx, wy)
    if l > 1e-6:
        wx, wy = wx / l * speed, wy / l * speed
    else:
        wx = wy = 0.0
    if jump and s["ground"]:
        s["vz"] = JUMP_V
        s["ground"] = False

    for axis, d in ((0, wx * dt), (1, wy * dt)):
        if not d:
            continue
        nx, ny = (s["x"] + d, s["y"]) if axis == 0 else (s["x"], s["y"] + d)
        hit = [b for b in boxes if _overlaps(nx, ny, s["z"], b)]
        if hit:
            top = max(b[2] + b[5] for b in hit)
            if s["ground"] and top - s["z"] <= STEP_H and _free(nx, ny, top + 0.001, boxes):
                s["x"], s["y"], s["z"] = nx, ny, top  # step up
                continue
            for b in hit:
                if axis == 0:
                    nx = b[0] - PLAYER_R - 1e-4 if d > 0 else b[0] + b[3] + PLAYER_R + 1e-4
                else:
                    ny = b[1] - PLAYER_R - 1e-4 if d > 0 else b[1] + b[4] + PLAYER_R + 1e-4
        s["x"], s["y"] = nx, ny

    s["vz"] -= GRAVITY * dt
    nz = s["z"] + s["vz"] * dt
    s["ground"] = False
    for b in boxes:
        if _overlaps(s["x"], s["y"], nz, b):
            if s["vz"] <= 0:
                nz = b[2] + b[5]
                s["ground"] = True
            else:
                nz = b[2] - PLAYER_H - 1e-4
            s["vz"] = 0.0
    if nz <= 0:
        nz = 0.0
        s["vz"] = 0.0
        s["ground"] = True
    s["z"] = nz
    w, d = size
    s["x"] = min(max(s["x"], PLAYER_R), w - PLAYER_R)
    s["y"] = min(max(s["y"], PLAYER_R), d - PLAYER_R)
    return s


def ray_box(o, d, b):
    tmin, tmax = 0.0, 1e9
    for i, (lo, size) in enumerate(((b[0], b[3]), (b[1], b[4]), (b[2], b[5]))):
        if abs(d[i]) < 1e-9:
            if o[i] < lo or o[i] > lo + size:
                return None
        else:
            t1, t2 = (lo - o[i]) / d[i], (lo + size - o[i]) / d[i]
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return None
    return tmin


def ray_sphere(o, d, c, r):
    ox, oy, oz = o[0] - c[0], o[1] - c[1], o[2] - c[2]
    b = ox * d[0] + oy * d[1] + oz * d[2]
    cc = ox * ox + oy * oy + oz * oz - r * r
    disc = b * b - cc
    if disc < 0:
        return None
    t = -b - math.sqrt(disc)
    return t if t >= 0 else None


def ray_cylinder(o, d, cx, cy, z0, z1, r):
    ox, oy = o[0] - cx, o[1] - cy
    a = d[0] * d[0] + d[1] * d[1]
    if a < 1e-9:
        return None
    b = 2 * (ox * d[0] + oy * d[1])
    c = ox * ox + oy * oy - r * r
    disc = b * b - 4 * a * c
    if disc < 0:
        return None
    t = (-b - math.sqrt(disc)) / (2 * a)
    if t < 0:
        return None
    z = o[2] + d[2] * t
    return t if z0 <= z <= z1 else None


def ray_world(o, d, boxes, max_t):
    best = max_t
    hit = False
    if d[2] < -1e-6:  # ground
        t = -o[2] / d[2]
        if 0 <= t < best:
            best, hit = t, True
    for b in boxes:
        t = ray_box(o, d, b)
        if t is not None and t < best:
            best, hit = t, True
    return best, hit


def line_of_sight(a, b, boxes):
    d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    L = math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2)
    if L < 1e-6:
        return True
    d = (d[0] / L, d[1] / L, d[2] / L)
    t, _ = ray_world(a, d, boxes, L)
    return t >= L - 1e-3


def spread_dir(h, p, cone_deg, rng=random):
    """Random direction inside a cone around heading/pitch."""
    a = rng.uniform(0, math.tau)
    r = math.sqrt(rng.random()) * cone_deg / 2
    return aim_vec(h + math.cos(a) * r, p + math.sin(a) * r)
