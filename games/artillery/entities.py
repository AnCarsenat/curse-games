"""Units (guns on the map), targets and explosions."""
import math
from dataclasses import dataclass

from .config import DUEL_HP
from .world import height, view_surface
from .content import SHELLS
from .physics import Projectile


# ------------------------------------------------------------------ entities
class Unit:
    def __init__(self, gun, x, y, name="", color=0):
        self.x, self.y = x, y
        self.az = 0.0
        self.elev = 45.0
        self.name, self.color = name, color   # duel: player label and color pair
        self.flip = False   # view looks backwards so east stays on the right of the screen
        self.hp = DUEL_HP
        self.fuel = gun.fuel
        self.cooldown = 0.0
        self.set_gun(gun)

    def set_gun(self, gun):
        """Change this unit's type in place (position and heading are kept)."""
        self.gun = gun
        self.ci = min(getattr(self, "ci", 0), len(gun.charges) - 1)
        self.si = 0
        self.fuse_time = self.shell.fuse_time
        self.elev = max(gun.elev_min, min(gun.elev_max, self.elev))

    @property
    def shell(self):
        return SHELLS[self.gun.shells[self.si]]

    @property
    def charge(self):
        return self.gun.charges[self.ci]

    @property
    def z(self):
        return height(self.x, self.y) + 3

    def make_projectile(self, wind=(0.0, 0.0)):
        e, a = math.radians(self.elev), math.radians(self.az)
        v = self.charge.velocity
        vel = (v * math.cos(e) * math.cos(a), v * math.cos(e) * math.sin(a), v * math.sin(e))
        return Projectile((self.x, self.y, self.z), vel, self.shell, self.fuse_time, wind)

    def predict(self):
        p = self.make_projectile()   # fire control does not know the wind
        p.surface = view_surface     # never stall the frame generating terrain
        path = []
        while p.result is None:
            p.step()
            path.append(p.pos)
        return path, p


@dataclass
class Target:
    x: float
    y: float
    alive: bool = True

    @property
    def z(self):
        return height(self.x, self.y) + 1


@dataclass
class Explosion:
    pos: tuple
    radius: float
    ttl: float = 0.8
