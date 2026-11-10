"""Synthesizes sound effects to WAV files on first launch (no audio assets needed)."""
import math
import os
import random
import struct
import wave

from panda3d.core import Filename

RATE = 22050


def _noise(length, decay, low=0.0, tone=0.0, tone_decay=30.0, vol=0.8, slide=0.0):
    out, prev = [], 0.0
    for i in range(int(RATE * length)):
        t = i / RATE
        env = math.exp(-t * decay)
        prev = prev * low + random.uniform(-1, 1) * (1 - low)
        s = prev * env
        if tone:
            s += math.sin(2 * math.pi * (tone + slide * t) * t) * math.exp(-t * tone_decay) * 0.6
        out.append(s * vol)
    return out


def _tone(freq, length, vol=0.4, decay=8.0, slide=0.0):
    return [math.sin(2 * math.pi * (freq + slide * i / RATE) * i / RATE) * math.exp(-i / RATE * decay) * vol
            for i in range(int(RATE * length))]


RECIPES = {
    "shot_light": lambda: _noise(0.12, 38, 0.2, 240, vol=0.55),
    "shot_medium": lambda: _noise(0.2, 26, 0.35, 150, vol=0.7),
    "shot_heavy": lambda: _noise(0.38, 12, 0.6, 85, 16, vol=0.95),
    "shot_rail": lambda: _tone(1800, 0.35, 0.35, 9, -3500) + [0.0] * 200,
    "boom": lambda: _noise(0.9, 5, 0.88, 50, 5, vol=1.0),
    "hit": lambda: _tone(1500, 0.05, 0.35, 60),
    "headshot": lambda: _tone(2200, 0.08, 0.4, 40) + _tone(2900, 0.08, 0.3, 40),
    "hurt": lambda: _noise(0.12, 28, 0.75, 260, vol=0.55),
    "kill": lambda: _tone(880, 0.12, 0.35, 12) + _tone(1320, 0.22, 0.35, 9),
    "reload": lambda: _noise(0.04, 90, 0.1, vol=0.4) + [0.0] * 3000 + _noise(0.05, 80, 0.1, vol=0.5),
    "gate_good": lambda: _tone(660, 0.08, 0.3, 14) + _tone(990, 0.16, 0.3, 10),
    "gate_bad": lambda: _tone(330, 0.1, 0.35, 10) + _tone(220, 0.2, 0.35, 8),
    "part": lambda: _tone(523, 0.07, 0.3, 10) + _tone(659, 0.07, 0.3, 10) + _tone(784, 0.2, 0.32, 7),
    "crash": lambda: _noise(0.35, 10, 0.7, 70, 10, vol=0.9),
    "tick": lambda: _noise(0.02, 120, 0.0, vol=0.25),
    "click": lambda: _tone(700, 0.04, 0.25, 60),
    "beep": lambda: _tone(880, 0.15, 0.35, 6),
    "go": lambda: _tone(1320, 0.4, 0.4, 4),
    "cash": lambda: _tone(1568, 0.06, 0.3, 30) + _tone(2093, 0.18, 0.3, 14),
    "craft": lambda: _noise(0.06, 60, 0.2, 500, vol=0.5) + [0.0] * 1500 + _noise(0.06, 60, 0.2, 400, vol=0.5) + [0.0] * 1500 + _tone(880, 0.2, 0.3, 10),
    "groan": lambda: _tone(110, 0.6, 0.35, 3, -40),
    "stab": lambda: _noise(0.08, 40, 0.3, 300, vol=0.6),
    "step": lambda: _noise(0.07, 55, 0.82, 95, 45, vol=0.6),
    "growl": lambda: [a + b for a, b in zip(_tone(95, 0.45, 0.4, 5, -30), _noise(0.45, 7, 0.9, vol=0.5))],
    "stinger": lambda: [a + b for a, b in zip(_tone(110, 1.6, 0.45, 1.6, -25), _tone(116, 1.6, 0.4, 1.4, -22))],
    "win": lambda: _tone(523, 0.15, 0.3, 4) + _tone(659, 0.15, 0.3, 4) + _tone(784, 0.15, 0.3, 4) + _tone(1046, 0.5, 0.35, 3),
}


def _write(path, samples):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples))


class Sounds:
    def __init__(self, base, cache_dir):
        self.base = base
        self.volume = 0.7
        self.sfx = {}
        os.makedirs(cache_dir, exist_ok=True)
        for name, recipe in RECIPES.items():
            path = os.path.join(cache_dir, f"{name}.wav")
            if not os.path.isfile(path):
                try:
                    _write(path, recipe())
                except OSError:
                    continue
            try:
                s = base.loader.loadSfx(Filename.fromOsSpecific(path))
                if s:
                    self.sfx[name] = [s] + [base.loader.loadSfx(Filename.fromOsSpecific(path)) for _ in range(3)]
            except Exception:
                pass
        self.rr = {k: 0 for k in self.sfx}

    def play(self, name, vol=1.0, rate=1.0):
        pool = self.sfx.get(name)
        if not pool:
            return
        i = self.rr[name] = (self.rr[name] + 1) % len(pool)
        s = pool[i]
        s.setVolume(max(0.0, min(1.0, vol * self.volume)))
        s.setPlayRate(rate)
        s.play()

    def shot(self, stats, vol=1.0):
        dmg = stats["damage"] * stats["pellets"] if stats else 15
        if stats and stats.get("explosionRadius", 0) > 0:
            name = "shot_heavy"
        elif stats and stats["damage"] >= 80:
            name = "shot_rail"
        else:
            name = "shot_light" if dmg < 16 else "shot_medium" if dmg < 45 else "shot_heavy"
        self.play(name, vol, random.uniform(0.92, 1.08))
