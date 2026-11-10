"""Grid navigation for zombies: one flow field per target, so any number of zombies path around walls cheaply.

The arena is cut into 1 m cells, each with the height of whatever stands on it (0 = ground). Zombies can walk
between cells of similar height, hop up ledges of up to JUMP_UP metres and drop down from anything.
field(x, y) floods outward from the target; direction(field, x, y) then says which way is downhill from anywhere.
"""
import math
from collections import deque

from .sim import PLAYER_H, PLAYER_R, STEP_H

JUMP_UP = 1.3        # ledges up to this much higher can be jumped onto (a jump peaks at about 1.45 m)
CLIMB_COST = 2.0     # extra path cost for a jump, so zombies prefer walking around when that's about as short
NEIGH = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142))
FAR = 1e9


class NavGrid:
    def __init__(self, size, boxes, cell=1.0, radius=PLAYER_R):
        self.cell = cell
        self.w = max(1, int(math.ceil(size[0] / cell)))
        self.h = max(1, int(math.ceil(size[1] / cell)))
        self.height = [0.0] * (self.w * self.h)
        pad = radius * 0.9
        for b in boxes:
            bx, by, bz, bw, bd, bh = b
            if bz + bh <= STEP_H or bz >= PLAYER_H:      # low enough to step on, or overhead with room beneath
                continue
            x0, x1 = int(math.floor((bx - pad) / cell)), int(math.floor((bx + bw + pad) / cell))
            y0, y1 = int(math.floor((by - pad) / cell)), int(math.floor((by + bd + pad) / cell))
            for cy in range(max(0, y0), min(self.h - 1, y1) + 1):
                cyc = (cy + 0.5) * cell
                if not (by - pad < cyc < by + bd + pad):
                    continue
                for cx in range(max(0, x0), min(self.w - 1, x1) + 1):
                    cxc = (cx + 0.5) * cell
                    if bx - pad < cxc < bx + bw + pad:    # the cell centre is inside the padded box
                        i = cy * self.w + cx
                        self.height[i] = max(self.height[i], bz + bh)

    def cell_of(self, x, y):
        return (min(self.w - 1, max(0, int(x / self.cell))), min(self.h - 1, max(0, int(y / self.cell))))

    def _flood(self, dist, sources):
        w, h, height = self.w, self.h, self.height
        q = deque()
        for sx, sy in sources:
            dist[sy * w + sx] = 0.0
            q.append((sx, sy))
        while q:
            cx, cy = q.popleft()
            ci = cy * w + cx
            d, hc = dist[ci], height[ci]
            for dx, dy, cost in NEIGH:
                nx, ny = cx + dx, cy + dy
                if nx < 0 or ny < 0 or nx >= w or ny >= h:
                    continue
                ni = ny * w + nx
                hn = height[ni]
                # the flood runs backwards from the target: a zombie would step from n to c
                if hc - hn > JUMP_UP:
                    continue                      # too high to jump up
                if dx and dy and (hc != hn or height[cy * w + nx] != hc or height[ny * w + cx] != hc):
                    continue                      # no cutting corners diagonally across ledge edges
                nd = d + cost + (CLIMB_COST if hc - hn > STEP_H else 0.0)
                if nd < dist[ni] - 1e-9:
                    dist[ni] = nd
                    q.append((nx, ny))

    def field(self, x, y):
        """Walking distance (in cells) from every cell to (x, y)."""
        w, h = self.w, self.h
        dist = [FAR] * (w * h)
        sx, sy = self.cell_of(x, y)
        self._flood(dist, [(sx, sy)])
        if sum(1 for d in dist if d < FAR) < 40:
            # the target stands somewhere zombies can't climb to (a container roof): gather below it instead
            for r in range(1, 9):
                ring = [(sx + dx, sy + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                        if max(abs(dx), abs(dy)) == r and 0 <= sx + dx < w and 0 <= sy + dy < h
                        and dist[(sy + dy) * w + sx + dx] >= FAR and self.height[(sy + dy) * w + sx + dx] <= STEP_H]
                if ring:
                    self._flood(dist, ring)
                    break
        return dist

    def distance(self, field, x, y):
        cx, cy = self.cell_of(x, y)
        return field[cy * self.w + cx]

    def direction(self, field, x, y):
        """(dx, dy, height of the next cell) toward the field's target, or None when there is no way."""
        w, h, height = self.w, self.h, self.height
        cx, cy = self.cell_of(x, y)
        ci = cy * w + cx
        best, bd, hc = None, field[ci], height[ci]
        for dx, dy, _ in NEIGH:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or ny < 0 or nx >= w or ny >= h:
                continue
            ni = ny * w + nx
            if height[ni] - hc > JUMP_UP:
                continue
            if dx and dy and (height[ni] != hc or height[cy * w + nx] != hc or height[ny * w + cx] != hc):
                continue
            if field[ni] < bd - 1e-9:
                best, bd = (nx, ny), field[ni]
        if best is None:
            return None
        tx, ty = (best[0] + 0.5) * self.cell, (best[1] + 0.5) * self.cell
        vx, vy = tx - x, ty - y
        L = math.hypot(vx, vy)
        return (vx / L, vy / L, height[best[1] * w + best[0]]) if L > 1e-6 else None
