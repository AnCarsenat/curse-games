"""Guns, shells and fuses. Add entries here to extend the game."""
from dataclasses import dataclass

from .config import MOVE_BUDGET


# ------------------------------------------------------------------ CONTENT
@dataclass
class Shell:
    name: str
    fuse: str                # key into FUSES
    blast: float             # blast radius (m)
    drag: float              # quadratic drag coefficient (1/m)
    fuse_time: float = 0.0   # default setting for timed fuses (s)
    char: str = "o"
    crater: float = 15.0     # crater depth (m) for a burst at ground level
    damage: float = 60.0     # duel: damage right on a unit (30% at the blast edge)


@dataclass
class Charge:
    name: str
    velocity: float          # muzzle velocity (m/s)


@dataclass
class Gun:
    name: str
    char: str
    charges: list
    shells: list             # keys into SHELLS
    mobile: bool = False
    prediction: bool = False  # fire-control computer shows the predicted arc
    sight: bool = False       # gunsight: shows roughly where the shot lands (end of the arc)
    elev_min: float = 0.0
    elev_max: float = 80.0
    reload: float = 2.0      # seconds (real time)
    speed: float = 15.0      # metres per move keypress
    fuel: float = MOVE_BUDGET  # duel: metres it may drive per turn

    @property
    def direct(self):
        """Direct-fire only (cannot elevate past 45 deg): firing table uses low angle."""
        return self.elev_max <= 45


FUSES = {
    "impact": lambda p: False,
    "timed": lambda p: p.t >= p.fuse_time,
    # arms after 2 s, bursts when falling within 12 m of the ground
    "proximity": lambda p: p.t > 2 and p.vz < 0 and p.z - p.surface(p.x, p.y) < 12,
}


SHELLS = {
    "HE":   Shell("HE", "impact", blast=30, drag=0.00006, crater=20),
    "AB":   Shell("Airburst", "timed", blast=45, drag=0.00006, fuse_time=8.0, char="*", crater=8),
    "VT":   Shell("Proximity", "proximity", blast=40, drag=0.00007, char="v", crater=8),
    "BOMB": Shell("Mortar bomb", "impact", blast=45, drag=0.0001, char="0", crater=25),
    "MAB":  Shell("Mortar airburst", "timed", blast=55, drag=0.0001, fuse_time=20.0, char="*", crater=10),
    "AP":   Shell("AP shot", "impact", blast=10, drag=0.0001, char="-", crater=4, damage=90),
    "HEAT": Shell("Tank HE", "impact", blast=25, drag=0.00008, char="o", crater=10, damage=55),
    "LRHE": Shell("Long-range HE", "impact", blast=40, drag=0.00004, char="O", crater=25),
    "LRAB": Shell("Long-range airburst", "timed", blast=55, drag=0.00004, fuse_time=30.0,
                  char="*", crater=10),
}


GUNS = [
    Gun("Field howitzer", "H",
        [Charge("1", 85), Charge("2", 115), Charge("3", 145)],
        ["HE", "AB"]),
    Gun("Self-propelled gun", "S",
        [Charge("low", 95), Charge("high", 130)],
        ["HE", "VT", "AB"], mobile=True, prediction=True, reload=3.0),
    Gun("Mortar", "m",
        [Charge("0", 80), Charge("1", 110), Charge("2", 140), Charge("3", 170)],
        ["BOMB", "MAB"], elev_min=45, elev_max=85, reload=1.0),
    Gun("Tank", "K",
        [Charge("std", 550)],
        ["AP", "HEAT"], mobile=True, sight=True, elev_min=-5, elev_max=12, reload=4.0, speed=40, fuel=400),
    Gun("Long-range howitzer", "L",
        [Charge("1", 200), Charge("2", 280), Charge("3", 360)],
        ["LRHE", "LRAB"], elev_min=0, elev_max=70, reload=6.0),
]
