"""Projectile flight and firing tables."""
import math

from .config import DT, G, MAX_FLIGHT, WIND_PUSH
from .world import height
from .content import FUSES


# ------------------------------------------------------------------ physics
class Projectile:
    def __init__(self, pos, vel, shell, fuse_time, wind=(0.0, 0.0)):
        self.x, self.y, self.z = pos
        self.wind = wind
        self.vx, self.vy, self.vz = vel
        self.shell = shell
        self.fuse_time = fuse_time
        self.t = 0.0
        self.result = None   # None while flying, then impact/airburst/lost
        self.trail = []
        self.surface = height   # predictions swap in a non-blocking version

    @property
    def pos(self):
        return (self.x, self.y, self.z)

    def step(self):
        sp = math.sqrt(self.vx ** 2 + self.vy ** 2 + self.vz ** 2)
        k = self.shell.drag * sp
        self.vx -= (k * self.vx - WIND_PUSH * self.wind[0]) * DT
        self.vy -= (k * self.vy - WIND_PUSH * self.wind[1]) * DT
        self.vz -= (G + k * self.vz) * DT
        self.x += self.vx * DT
        self.y += self.vy * DT
        self.z += self.vz * DT
        self.t += DT
        surf = self.surface(self.x, self.y)
        if self.z <= surf:
            self.z = surf
            self.result = "impact"
        elif FUSES[self.shell.fuse](self):
            self.result = "airburst"
        elif self.t > MAX_FLIGHT:
            self.result = "lost"
        return self.result


_table_cache = {}


def firing_table(v, drag):
    """Flat-ground (range, time of flight) for elevations 0..90 deg."""
    key = (v, drag)
    if key not in _table_cache:
        rows = []
        for e in range(91):
            a = math.radians(e)
            vx, vz = v * math.cos(a), v * math.sin(a)
            x = z = t = 0.0
            while True:
                k = drag * math.hypot(vx, vz)
                vx -= k * vx * DT
                vz -= (G + k * vz) * DT
                x += vx * DT
                z += vz * DT
                t += DT
                if z < 0:
                    break
            rows.append((x, t))
        _table_cache[key] = rows
    return _table_cache[key]


def high_angle(rows, rng):
    """Indirect (high-angle) solution for a flat-ground range: (elev, tof) or None."""
    peak = max(range(91), key=lambda e: rows[e][0])
    for e in range(90, peak, -1):          # range grows as elevation drops to the peak
        r_hi, r_lo = rows[e][0], rows[e - 1][0]
        if r_hi <= rng <= r_lo:
            f = (rng - r_hi) / ((r_lo - r_hi) or 1)
            return e - f, rows[e][1] * (1 - f) + rows[e - 1][1] * f
    return None


def low_angle(rows, rng):
    """Direct (low-angle) solution for a flat-ground range: (elev, tof) or None."""
    peak = max(range(91), key=lambda e: rows[e][0])
    for e in range(peak):
        r_lo, r_hi = rows[e][0], rows[e + 1][0]
        if r_lo <= rng <= r_hi:
            f = (rng - r_lo) / ((r_hi - r_lo) or 1)
            return e + f, rows[e][1] * (1 - f) + rows[e + 1][1] * f
    return None


def slope_char(deg):
    """ASCII line character for a direction in degrees (0 = right, counter-clockwise)."""
    deg %= 180
    return "-" if deg < 22.5 or deg >= 157.5 else "/" if deg < 67.5 else "|" if deg < 112.5 else "\\"


def table_lookup(rows, elev, idx):
    elev = max(0.0, min(90.0, elev))
    e0 = max(0, min(89, int(elev)))
    f = elev - e0
    return rows[e0][idx] * (1 - f) + rows[e0 + 1][idx] * f
