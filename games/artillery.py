#!/usr/bin/env python3
"""
artillery.py - tiny curses artillery sandbox.

Run:  python3 artillery.py      (press ? in game for keys)

Extending: add entries to FUSES, SHELLS and GUNS in the CONTENT section.
  - A fuse is a function(projectile) -> bool (True = detonate in the air).
    Ground contact always detonates.
  - A shell picks a fuse by key and sets blast radius, drag, default fuse time.
  - A gun lists its charges (muzzle velocities), which shells it can load,
    whether it is mobile, whether it has fire-control prediction, and limits.
"""
import curses
import json
import locale
import os
import math
import random
import time
from dataclasses import dataclass

# ------------------------------------------------------------------ constants
G = 9.81            # gravity m/s^2
WORLD = 2400.0      # world is WORLD x WORLD metres
Y0 = WORLD / 2      # starting line of the units
Z_MAX = 900.0       # altitude at the top of the view (m)
DT = 0.05           # physics step (s)
TIME_SCALE = 4.0    # simulated seconds per real second
MAX_FLIGHT = 120.0  # shells older than this are discarded


def base_height(x, y):
    """Undamaged terrain altitude at (x, y)."""
    return (120 + 40 * math.sin(x / 170) + 25 * math.sin(x / 67 + 1.3)
            + 30 * math.sin(y / 210 + 0.5) + 20 * math.sin((x + y) / 120))


# Terrain damage: a grid of height offsets (m), bilinearly interpolated.
CELL = 10.0
N_CELLS = int(WORLD / CELL) + 1
_deform = [[0.0] * N_CELLS for _ in range(N_CELLS)]   # _deform[ix][iy]


def deform(x, y):
    fx, fy = x / CELL, y / CELL
    if not (0 <= fx < N_CELLS - 1 and 0 <= fy < N_CELLS - 1):
        return 0.0
    ix, iy = int(fx), int(fy)
    tx, ty = fx - ix, fy - iy
    c0, c1 = _deform[ix], _deform[ix + 1]
    return ((c0[iy] * (1 - ty) + c0[iy + 1] * ty) * (1 - tx)
            + (c1[iy] * (1 - ty) + c1[iy + 1] * ty) * tx)


def height(x, y):
    """Current terrain altitude at (x, y), craters included."""
    return base_height(x, y) + deform(x, y)


def make_crater(x, y, radius, depth):
    """Dig a bowl of `radius` and `depth` with a small raised rim."""
    rim = radius * 1.4
    for ix in range(max(0, int((x - rim) / CELL)), min(N_CELLS, int((x + rim) / CELL) + 2)):
        col = _deform[ix]
        for iy in range(max(0, int((y - rim) / CELL)), min(N_CELLS, int((y + rim) / CELL) + 2)):
            d = math.hypot(ix * CELL - x, iy * CELL - y)
            if d < radius:
                col[iy] -= depth * (1 - (d / radius) ** 2)
            elif d < rim:
                col[iy] += depth * 0.25 * math.sin(math.pi * (d - radius) / (rim - radius))


def reset_terrain():
    for col in _deform:
        col[:] = [0.0] * N_CELLS


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
    elev_min: float = 0.0
    elev_max: float = 80.0
    reload: float = 2.0      # seconds (real time)
    speed: float = 15.0      # metres per move keypress


FUSES = {
    "impact": lambda p: False,
    "timed": lambda p: p.t >= p.fuse_time,
    # arms after 2 s, bursts when falling within 12 m of the ground
    "proximity": lambda p: p.t > 2 and p.vz < 0 and p.z - height(p.x, p.y) < 12,
}

SHELLS = {
    "HE":   Shell("HE", "impact", blast=30, drag=0.00006, crater=20),
    "AB":   Shell("Airburst", "timed", blast=45, drag=0.00006, fuse_time=8.0, char="*", crater=8),
    "VT":   Shell("Proximity", "proximity", blast=40, drag=0.00007, char="v", crater=8),
    "BOMB": Shell("Mortar bomb", "impact", blast=25, drag=0.00015, char="0", crater=12),
}

GUNS = [
    Gun("Field howitzer", "H",
        [Charge("1", 85), Charge("2", 115), Charge("3", 145)],
        ["HE", "AB"]),
    Gun("Self-propelled gun", "S",
        [Charge("low", 95), Charge("high", 130)],
        ["HE", "VT"], mobile=True, prediction=True, reload=3.0),
    Gun("Mortar", "m",
        [Charge("0", 45), Charge("1", 65), Charge("2", 85)],
        ["BOMB"], elev_min=45, elev_max=85, reload=1.0),
]


# ------------------------------------------------------------------ physics
class Projectile:
    def __init__(self, pos, vel, shell, fuse_time):
        self.x, self.y, self.z = pos
        self.vx, self.vy, self.vz = vel
        self.shell = shell
        self.fuse_time = fuse_time
        self.t = 0.0
        self.result = None   # None while flying, then impact/airburst/lost
        self.trail = []

    @property
    def pos(self):
        return (self.x, self.y, self.z)

    def step(self):
        sp = math.sqrt(self.vx ** 2 + self.vy ** 2 + self.vz ** 2)
        k = self.shell.drag * sp
        self.vx -= k * self.vx * DT
        self.vy -= k * self.vy * DT
        self.vz -= (G + k * self.vz) * DT
        self.x += self.vx * DT
        self.y += self.vy * DT
        self.z += self.vz * DT
        self.t += DT
        ground = height(self.x, self.y)
        if self.z <= ground:
            self.z = ground
            self.result = "impact"
        elif FUSES[self.shell.fuse](self):
            self.result = "airburst"
        elif (not (-300 < self.x < WORLD + 300 and -300 < self.y < WORLD + 300)
              or self.t > MAX_FLIGHT):
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


def table_lookup(rows, elev, idx):
    e0 = max(0, min(89, int(elev)))
    f = elev - e0
    return rows[e0][idx] * (1 - f) + rows[e0 + 1][idx] * f


# ------------------------------------------------------------------ entities
class Unit:
    def __init__(self, gun, x, y):
        self.gun = gun
        self.x, self.y = x, y
        self.az = 0.0
        self.elev = max(gun.elev_min, min(gun.elev_max, 45.0))
        self.ci = 0
        self.si = 0
        self.fuse_time = self.shell.fuse_time
        self.cooldown = 0.0

    @property
    def shell(self):
        return SHELLS[self.gun.shells[self.si]]

    @property
    def charge(self):
        return self.gun.charges[self.ci]

    @property
    def z(self):
        return height(self.x, self.y) + 3

    def make_projectile(self):
        e, a = math.radians(self.elev), math.radians(self.az)
        v = self.charge.velocity
        vel = (v * math.cos(e) * math.cos(a), v * math.cos(e) * math.sin(a), v * math.sin(e))
        return Projectile((self.x, self.y, self.z), vel, self.shell, self.fuse_time)

    def predict(self):
        p = self.make_projectile()
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


# ------------------------------------------------------------------ game
# ------------------------------------------------------------------ key bindings
# Every key goes through an action name. Defaults = COMMON_KEYS + the layout,
# and per-action overrides (in-game "Key bindings" menu or the JSON file) win.
ACTIONS = [   # (action, description) - order used by the help and key menu
    ("left",            "drive back / turn left"),
    ("right",           "drive forward / turn right"),
    ("forward",         "free cam forward, menu up"),
    ("back",            "free cam back, menu down"),
    ("turn_fine_left",  "fine turn left 1 deg"),
    ("turn_fine_right", "fine turn right 1 deg"),
    ("elev_up",         "elevation +1"),
    ("elev_down",       "elevation -1"),
    ("elev_up5",        "elevation +5"),
    ("elev_down5",      "elevation -5"),
    ("fire",            "fire"),
    ("charge_next",     "next charge"),
    ("charge_prev",     "previous charge"),
    ("shell_next",      "load next shell"),
    ("fuse_down",       "fuse time -0.5 s"),
    ("fuse_up",         "fuse time +0.5 s"),
    ("next_unit",       "switch unit"),
    ("mode",            "MOVE <-> ROTATE (minimap)"),
    ("graph",           "graph range/tof/off"),
    ("gauge",           "pitch/yaw gauge"),
    ("freecam",         "free camera"),
    ("new_targets",     "new targets"),
    ("repair",          "repair terrain"),
    ("menu",            "configuration menu"),
    ("help",            "help"),
    ("quit",            "quit"),
]
ACTION_IDS = {a for a, _ in ACTIONS}

COMMON_KEYS = {
    "left": ["left"], "right": ["right"],
    "elev_up": ["up"], "elev_down": ["down"], "elev_up5": ["pgup"], "elev_down5": ["pgdn"],
    "fire": ["space", "f"], "charge_next": ["c"], "charge_prev": ["C"], "shell_next": ["l"],
    "next_unit": ["tab"], "mode": ["t"], "graph": ["g"], "gauge": ["p"], "freecam": ["v"],
    "new_targets": ["n"], "repair": ["r"], "menu": ["m"], "help": ["?", "h"],
}

LAYOUTS = {   # layout id -> (display name, layout-specific keys)
    "azerty": ("AZERTY (ZQSD)", {
        "forward": ["z"], "back": ["s"], "left": ["q"], "right": ["d"],
        "turn_fine_left": [","], "turn_fine_right": [";"],
        "fuse_down": ["("], "fuse_up": [")"], "quit": ["Q"],
    }),
    "wasd": ("QWERTY (WASD)", {
        "forward": ["w"], "back": ["s"], "left": ["a"], "right": ["d"],
        "turn_fine_left": [","], "turn_fine_right": ["."],
        "fuse_down": ["["], "fuse_up": ["]"], "quit": ["q"],
    }),
}

SPECIAL_KEYS = {
    "space": 32, "tab": 9, "enter": 10, "esc": 27,
    "up": curses.KEY_UP, "down": curses.KEY_DOWN, "left": curses.KEY_LEFT,
    "right": curses.KEY_RIGHT, "pgup": curses.KEY_PPAGE, "pgdn": curses.KEY_NPAGE,
    "home": curses.KEY_HOME, "end": curses.KEY_END, "ins": curses.KEY_IC, "del": curses.KEY_DC,
    "backspace": curses.KEY_BACKSPACE,
}
BACKSPACE_CODES = (curses.KEY_BACKSPACE, 127, 8)
KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artillery_keys.json")


def key_code(name):
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    if name.startswith("key") and name[3:].isdigit():
        return int(name[3:])
    if len(name) == 1:
        return ord(name)
    raise ValueError(f"unknown key name {name!r}")


def key_name(code):
    for n, c in SPECIAL_KEYS.items():
        if c == code:
            return n
    if 32 < code < 127:
        return chr(code)
    return f"key{code}"


class Keymap:
    """Action <-> key lookup. Saved as JSON: {"layout": ..., "overrides": {action: [keys]}}."""

    def __init__(self, path=None):
        self.path = path or KEYS_FILE
        path = self.path
        self.layout = "azerty"
        self.overrides = {}
        self.error = None
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("layout") in LAYOUTS:
                self.layout = data["layout"]
            self.overrides = {a: [str(k) for k in v] for a, v in data.get("overrides", {}).items()
                              if a in ACTION_IDS}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, TypeError) as e:
            self.error = f"could not read {os.path.basename(path)}: {e}"
        self.rebuild()

    def defaults(self, action):
        return COMMON_KEYS.get(action, []) + LAYOUTS[self.layout][1].get(action, [])

    def keys(self, action):
        return self.overrides.get(action, self.defaults(action))

    def rebuild(self):
        self.lookup = {}
        # overridden actions claim their keys first, so a custom binding always wins
        order = sorted((a for a, _ in ACTIONS), key=lambda a: a not in self.overrides)
        for a in order:
            for n in self.keys(a):
                try:
                    self.lookup.setdefault(key_code(n), a)
                except ValueError:
                    self.error = f"unknown key name {n!r} for {a}"

    def action(self, code):
        return self.lookup.get(code)

    def label(self, action):
        return "/".join(self.keys(action)) or "-"

    def bind(self, action, code):
        """Make `code` the only key of `action`, removing it from other actions."""
        name = key_name(code)
        for a, _ in ACTIONS:
            if a != action and name in self.keys(a):
                self.overrides[a] = [n for n in self.keys(a) if n != name]
        self.overrides[action] = [name]
        self.rebuild()
        self.save()

    def reset(self, action):
        self.overrides.pop(action, None)
        self.rebuild()
        self.save()

    def set_layout(self, layout):
        self.layout = layout
        self.rebuild()
        self.save()

    def save(self):
        try:
            with open(self.path, "w") as f:
                json.dump({"layout": self.layout, "overrides": self.overrides}, f, indent=2)
        except OSError as e:
            self.error = f"could not save keys: {e}"


HELP_NOTES = [
    "MOVE mode: left/right drive along the heading (mobile units only).",
    "ROTATE mode: left/right turn the gun, minimap shown. Heading is kept.",
    "The view is a vertical slice of the world along the gun heading.",
    "Units with FCS show the predicted arc (cyan); others use graph + ruler.",
    "Rebind keys: menu > Key bindings, or edit artillery_keys.json.",
]


class Game:
    def __init__(self):
        self.units = [Unit(g, 150 + 150 * i, Y0) for i, g in enumerate(GUNS)]
        self.ui = 0
        self.rotate = False     # False = MOVE mode, True = ROTATE mode
        self.freecam = False
        self.cam = [0.0, Y0, 0.0]
        self.graph = 0          # 0 off, 1 range, 2 time of flight
        self.help = False
        self.menu = None        # selected row while the config menu is open
        self.keymenu = None     # selected action while the key-binding page is open
        self.capturing = False  # waiting for a key to bind
        self.gauge = True
        self.keys = Keymap()
        self.projectiles = []
        self.explosions = []
        self.shots = 0
        self.say(self.keys.error or f"{self.keys.label('help')}: help   {self.keys.label('menu')}: menu", 5)
        self.acc = 0.0
        self.minimap = None
        self.spawn_targets()

    @property
    def unit(self):
        return self.units[self.ui]

    def say(self, text, t=3.0):
        self.msg, self.msg_t = text, t

    def spawn_targets(self):
        self.targets = [Target(random.uniform(700, 2300), random.uniform(200, 2200))
                        for _ in range(6)]
        self.shots = 0

    # ---------------------------------------------------------- input
    def key(self, k):
        act = self.keys.action(k)
        if self.menu is not None:
            return self.menu_key(k, act)
        u, gun = self.unit, self.unit.gun
        if act == "quit":
            return False
        if act == "menu":
            self.menu = 0
        elif act == "help":
            self.help = not self.help
        elif act in ("elev_up", "elev_down", "elev_up5", "elev_down5"):
            u.elev += {"elev_up": 1, "elev_down": -1, "elev_up5": 5, "elev_down5": -5}[act]
        elif act == "fire":
            self.fire()
        elif act == "charge_next":
            u.ci = (u.ci + 1) % len(gun.charges)
        elif act == "charge_prev":
            u.ci = (u.ci - 1) % len(gun.charges)
        elif act == "shell_next":
            u.si = (u.si + 1) % len(gun.shells)
            u.fuse_time = u.shell.fuse_time
            self.say(f"Loaded {u.shell.name}")
        elif act in ("fuse_down", "fuse_up"):
            if u.shell.fuse == "timed":
                u.fuse_time = max(0.5, u.fuse_time + (0.5 if act == "fuse_up" else -0.5))
            else:
                self.say(f"{u.shell.name} has a {u.shell.fuse} fuse, no timer")
        elif act == "next_unit":
            self.ui = (self.ui + 1) % len(self.units)
            self.say(f"Controlling {self.unit.gun.name}")
        elif act == "graph":
            self.graph = (self.graph + 1) % 3
        elif act == "mode":
            self.rotate = not self.rotate
            self.say("ROTATE mode: left/right turn the gun" if self.rotate
                     else f"MOVE mode: heading {u.az:.0f} kept")
        elif act == "freecam":
            self.freecam = not self.freecam
            self.cam = [u.x, u.y, u.az]
            self.say("Free camera" if self.freecam else "Camera follows unit")
        elif act == "new_targets":
            self.spawn_targets()
            self.say("New targets")
        elif act == "repair":
            reset_terrain()
            self.minimap = None
            self.say("Terrain repaired")
        elif act == "gauge":
            self.gauge = not self.gauge
        elif act in ("turn_fine_left", "turn_fine_right"):
            u.az = (u.az + (1 if act == "turn_fine_left" else -1)) % 360
        elif act in ("left", "right", "forward", "back"):
            self.move(act)
        u.elev = max(gun.elev_min, min(gun.elev_max, u.elev))
        return True

    def move(self, act):
        u = self.unit
        if self.freecam:
            a = math.radians(self.cam[2])
            if act == "left":
                self.cam[2] = (self.cam[2] + 3) % 360
            elif act == "right":
                self.cam[2] = (self.cam[2] - 3) % 360
            else:
                d = 40 if act == "forward" else -40
                self.cam[0] += math.cos(a) * d
                self.cam[1] += math.sin(a) * d
            return
        if act in ("forward", "back"):
            return
        direction = 1 if act == "right" else -1
        if self.rotate:
            # screen-left turns counter-clockwise on the map
            u.az = (u.az - 3 * direction) % 360
            return
        if not u.gun.mobile:
            self.say(f"{u.gun.name} is not mobile ({self.keys.label('mode')}: rotate mode)")
            return
        a = math.radians(u.az)     # forward is to the right of the slice view
        u.x = max(0, min(WORLD, u.x + direction * math.cos(a) * u.gun.speed))
        u.y = max(0, min(WORLD, u.y + direction * math.sin(a) * u.gun.speed))

    def fire(self):
        u = self.unit
        if u.cooldown > 0:
            self.say(f"Reloading ({u.cooldown:.1f}s)")
            return
        self.projectiles.append(u.make_projectile())
        u.cooldown = u.gun.reload
        self.shots += 1

    # ---------------------------------------------------------- config menu
    def menu_rows(self):
        """(label, value text, change(delta) or None). Add rows to expose more settings."""
        u, g = self.unit, self.unit.gun

        def set_unit(d):
            self.ui = (self.ui + d) % len(self.units)

        def set_shell(d):
            u.si = (u.si + d) % len(g.shells)
            u.fuse_time = u.shell.fuse_time

        def set_charge(d):
            u.ci = (u.ci + d) % len(g.charges)

        def set_fuse(d):
            u.fuse_time = max(0.5, u.fuse_time + 0.5 * d)

        def set_elev(d):
            u.elev = max(g.elev_min, min(g.elev_max, u.elev + d))

        def set_heading(d):
            u.az = (u.az - d) % 360

        def set_graph(d):
            self.graph = (self.graph + d) % 3

        def set_gauge(d):
            self.gauge = not self.gauge

        def set_layout(d):
            ids = list(LAYOUTS)
            self.keys.set_layout(ids[(ids.index(self.keys.layout) + d) % len(ids)])

        def open_keys(d):
            self.keymenu = 0

        timed = u.shell.fuse == "timed"
        return [
            ("Unit", f"{self.ui + 1}/{len(self.units)} {g.char} {g.name}", set_unit),
            ("Shell", f"{u.shell.name} ({u.shell.fuse} fuse)", set_shell),
            ("Charge", f"{u.charge.name} - {u.charge.velocity:.0f} m/s", set_charge),
            ("Fuse time", f"{u.fuse_time:.1f} s" if timed else "- (no timer on this fuse)",
             set_fuse if timed else None),
            ("Elevation", f"{u.elev:.0f} deg  (limits {g.elev_min:.0f}-{g.elev_max:.0f})", set_elev),
            ("Heading", f"{u.az:.0f} deg", set_heading),
            ("Graph", ["off", "range", "time of flight"][self.graph], set_graph),
            ("Gauge", "on" if self.gauge else "off", set_gauge),
            ("Layout", LAYOUTS[self.keys.layout][0], set_layout),
            ("Key bindings", "Enter to edit", open_keys),
        ]

    def menu_info(self):
        u, g, sh = self.unit, self.unit.gun, self.unit.shell
        yn = lambda b: "yes" if b else "no"
        charges = "  ".join(("[%s:%.0f]" if i == u.ci else " %s:%.0f ") % (c.name, c.velocity)
                            for i, c in enumerate(g.charges))
        shells = "  ".join(("[%s]" if i == u.si else " %s ") % SHELLS[k].name
                           for i, k in enumerate(g.shells))
        return [
            f"mobile {yn(g.mobile)}   fire control {yn(g.prediction)}   reload {g.reload:.1f} s",
            f"charges (m/s): {charges}",
            f"shells: {shells}",
            f"{sh.name}: blast {sh.blast:.0f} m, crater {sh.crater:.0f} m, drag {sh.drag:g}",
        ]

    def menu_key(self, k, act):
        up = k == curses.KEY_UP or act == "forward"
        down = k == curses.KEY_DOWN or act == "back"
        enter = k in (10, 13, curses.KEY_ENTER)
        esc = k == 27
        if self.keymenu is not None:
            return self.keymenu_key(k, up, down, enter, esc, act)
        rows = self.menu_rows()
        label, _, change = rows[self.menu]
        if enter and label == "Key bindings":
            change(1)
        elif esc or enter or act in ("menu", "quit"):
            self.menu = None
        elif up:
            self.menu = (self.menu - 1) % len(rows)
        elif down:
            self.menu = (self.menu + 1) % len(rows)
        else:
            d = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1,
                 curses.KEY_NPAGE: -5, curses.KEY_PPAGE: 5}.get(k) or {"left": -1, "right": 1}.get(act)
            if d and change:
                change(d)
        return True

    def keymenu_key(self, k, up, down, enter, esc, act):
        action, desc = ACTIONS[self.keymenu]
        if self.capturing:
            self.capturing = False
            if not esc:
                self.keys.bind(action, k)
                self.say(f"{desc}: {self.keys.label(action)}")
        elif esc or act == "menu":
            self.keymenu = None
        elif up:
            self.keymenu = (self.keymenu - 1) % len(ACTIONS)
        elif down:
            self.keymenu = (self.keymenu + 1) % len(ACTIONS)
        elif enter:
            self.capturing = True
        elif k in BACKSPACE_CODES or k == curses.KEY_DC:
            self.keys.reset(action)
        return True

    # ---------------------------------------------------------- update
    def update(self, rdt):
        if self.menu is not None:
            return              # game paused while configuring
        self.msg_t -= rdt
        for u in self.units:
            u.cooldown = max(0.0, u.cooldown - rdt)
        for e in self.explosions:
            e.ttl -= rdt
        self.explosions = [e for e in self.explosions if e.ttl > 0]
        self.acc += rdt * TIME_SCALE
        while self.acc >= DT:
            self.acc -= DT
            for p in self.projectiles:
                if p.result is None and p.step():
                    self.detonate(p)
            for p in self.projectiles:
                p.trail.append(p.pos)
                del p.trail[:-40]
            self.projectiles = [p for p in self.projectiles if p.result is None]

    def detonate(self, p):
        if p.result == "lost":
            self.say("Shell lost out of the map")
            return
        self.explosions.append(Explosion(p.pos, p.shell.blast))
        # crater: full depth at ground level, none once burst height >= blast radius
        agl = p.z - height(p.x, p.y)
        depth = p.shell.crater * max(0.0, 1 - agl / p.shell.blast)
        if depth > 0.5:
            make_crater(p.x, p.y, p.shell.blast, depth)
            self.minimap = None
        hits = 0
        for t in self.targets:
            if t.alive and math.dist(p.pos, (t.x, t.y, t.z)) <= p.shell.blast:
                t.alive = False
                hits += 1
        if hits:
            left = sum(t.alive for t in self.targets)
            self.say(f"HIT x{hits}!" + ("  All targets destroyed - n for more" if not left else ""))

    # ---------------------------------------------------------- view
    def view(self):
        """(cam_x, cam_y, heading_deg, s_start, span) of the vertical slice."""
        if self.freecam:
            cx, cy, az = self.cam
        else:
            cx, cy, az = self.unit.x, self.unit.y, self.unit.az
        return cx, cy, az, -250.0, 2200.0

    def project(self, x, y):
        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        dx, dy = x - cx, y - cy
        s = dx * math.cos(a) + dy * math.sin(a)
        off = -dx * math.sin(a) + dy * math.cos(a)
        col = int(round((s - s0) / span * (self.vw - 1)))
        return col, off, s

    def zrow(self, z):
        return self.vt + int(round((1 - z / Z_MAX) * (self.vh - 1)))

    # ---------------------------------------------------------- draw
    def put(self, y, x, s, attr=0):
        if 0 <= y < self.H and 0 <= x < self.W:
            try:
                self.scr.addstr(y, x, s[: self.W - x], attr)
            except curses.error:
                pass

    def draw(self, scr):
        self.scr = scr
        self.H, self.W = scr.getmaxyx()
        scr.erase()
        if self.H < 20 or self.W < 70:
            self.put(0, 0, "Terminal too small (need 70x20)")
            scr.refresh()
            return
        self.vt, self.vh, self.vw = 2, self.H - 3, self.W
        self.v = self.view()
        self.draw_terrain()
        self.draw_ruler()
        self.draw_targets()
        if self.unit.gun.prediction:
            self.draw_prediction()
        self.draw_projectiles()
        self.draw_units()
        self.draw_explosions()
        if self.rotate:
            self.draw_minimap()
        if self.gauge:
            self.draw_gauge()
        if self.graph:
            self.draw_graph()
        self.draw_hud()
        if self.menu is not None:
            self.draw_menu()
        if self.help:
            self.draw_help()
        scr.refresh()

    def draw_terrain(self):
        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        rows = [[" "] * self.vw for _ in range(self.vh)]
        scorched = []
        for col in range(self.vw):
            s = s0 + col / (self.vw - 1) * span
            x, y = cx + s * math.cos(a), cy + s * math.sin(a)
            if not (0 <= x <= WORLD and 0 <= y <= WORLD):
                rows[-1][col] = "~"
                continue
            dmg = deform(x, y)
            h = base_height(x, y) + dmg
            fz = (1 - h / Z_MAX) * (self.vh - 1)      # fractional row of the surface
            r = max(0, int(round(fz)))
            if r < self.vh:
                surf = "_" if fz - round(fz) > 0.15 else "#"   # surface in lower part of cell
                rows[r][col] = surf
                for rr in range(r + 1, self.vh):
                    rows[rr][col] = ":"
                if dmg < -1.5:
                    scorched.append((r, col, surf))
        green = curses.color_pair(1)
        for i, row in enumerate(rows):
            self.put(self.vt + i, 0, "".join(row), green)
        brown = curses.color_pair(3) | curses.A_DIM
        for r, col, surf in scorched:     # crater floors drawn in dim red
            self.put(self.vt + r, col, "w" if surf == "#" else "_", brown)

    def draw_ruler(self):
        """Distance ticks from the controlled unit along the view line."""
        _, _, _, s0, span = self.v
        _, _, su = self.project(self.unit.x, self.unit.y)
        row = self.vt + self.vh - 1
        for d in range(-2500, 2501, 250):
            col = int(round((su + d - s0) / span * (self.vw - 1)))
            if 0 <= col < self.vw:
                self.put(row, col, "|" if d else "^", curses.A_BOLD)
                if d and d % 500 == 0:
                    self.put(row, col + 1, str(abs(d)), curses.A_DIM)

    def draw_targets(self):
        for t in self.targets:
            col, off, _ = self.project(t.x, t.y)
            if abs(off) > 80:
                continue
            attr = curses.color_pair(5) | (curses.A_BOLD if abs(off) < 30 else curses.A_DIM)
            self.put(self.zrow(t.z), col, "T" if t.alive else "x", attr)

    def draw_units(self):
        _, _, vaz, _, _ = self.v
        for i, u in enumerate(self.units):
            col, off, _ = self.project(u.x, u.y)
            if abs(off) > 100:
                continue
            r = self.zrow(u.z)
            attr = curses.A_BOLD | (curses.A_REVERSE if i == self.ui else 0)
            self.put(r, col, u.gun.char, attr)
            right = math.cos(math.radians(u.az - vaz)) >= 0
            if u.elev < 25:
                b = "-"
            elif u.elev < 65:
                b = "/" if right else "\\"
            else:
                b = "|"
            self.put(r - 1, col + (1 if right else -1) if b != "|" else col, b, curses.A_BOLD)

    def draw_prediction(self):
        path, p = self.unit.predict()
        cyan = curses.color_pair(4)
        for pt in path[::3]:
            col, off, _ = self.project(pt[0], pt[1])
            self.put(self.zrow(pt[2]), col, ".", cyan)
        if p.result != "lost":
            col, _, _ = self.project(p.x, p.y)
            self.put(self.zrow(p.z), col, "X", cyan | curses.A_BOLD)
        self.prediction = (path, p)

    def draw_projectiles(self):
        yellow = curses.color_pair(2)
        for p in self.projectiles:
            for pt in p.trail[::2]:
                col, _, _ = self.project(pt[0], pt[1])
                self.put(self.zrow(pt[2]), col, "'", yellow | curses.A_DIM)
            col, off, _ = self.project(p.x, p.y)
            self.put(self.zrow(p.z), col, p.shell.char,
                     yellow | (curses.A_BOLD if abs(off) < 50 else curses.A_DIM))

    def draw_explosions(self):
        _, _, _, _, span = self.v
        red = curses.color_pair(3) | curses.A_BOLD
        for e in self.explosions:
            col, off, _ = self.project(e.pos[0], e.pos[1])
            if abs(off) > e.radius:
                continue
            row = self.zrow(e.pos[2])
            rc = max(1.0, e.radius / span * (self.vw - 1))
            rr = max(1.0, e.radius / Z_MAX * (self.vh - 1))
            for dr in range(-math.ceil(rr), math.ceil(rr) + 1):
                for dc in range(-math.ceil(rc), math.ceil(rc) + 1):
                    if (dc / rc) ** 2 + (dr / rr) ** 2 <= 1:
                        self.put(row + dr, col + dc, "*", red)

    def draw_minimap(self):
        mw, mh = 26, 13
        left, top = self.W - mw - 2, self.vt
        if self.minimap is None:
            shades = " .:-=+*#"
            self.minimap = []
            for j in range(mh):
                row = ""
                for i in range(mw):
                    h = height((i + 0.5) / mw * WORLD, (1 - (j + 0.5) / mh) * WORLD)
                    row += shades[max(0, min(len(shades) - 1, int(h / 240 * len(shades))))]
                self.minimap.append(row)

        def cell(x, y):
            return left + 1 + int(x / WORLD * mw), top + 1 + int((1 - y / WORLD) * mh)

        self.put(top, left, "+" + "-" * mw + "+", curses.A_DIM)
        self.put(top, left + 2, " map ", curses.A_BOLD)
        for j, row in enumerate(self.minimap):
            self.put(top + 1 + j, left, "|", curses.A_DIM)
            self.put(top + 1 + j, left + 1, row, curses.color_pair(1) | curses.A_DIM)
            self.put(top + 1 + j, left + 1 + mw, "|", curses.A_DIM)
        self.put(top + mh + 1, left, "+" + "-" * mw + "+", curses.A_DIM)

        def inside(c, r):
            return left < c <= left + mw and top < r <= top + mh

        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        for k in range(40):
            s = s0 + k / 39 * span
            c, r = cell(cx + s * math.cos(a), cy + s * math.sin(a))
            if inside(c, r):
                self.put(r, c, "`", curses.color_pair(4))
        for t in self.targets:
            c, r = cell(t.x, t.y)
            if inside(c, r):
                self.put(r, c, "T" if t.alive else "x", curses.color_pair(5) | curses.A_BOLD)
        for p in self.projectiles:
            c, r = cell(p.x, p.y)
            if inside(c, r):
                self.put(r, c, "o", curses.color_pair(2) | curses.A_BOLD)
        for i, u in enumerate(self.units):
            c, r = cell(u.x, u.y)
            if inside(c, r):
                self.put(r, c, u.gun.char, curses.A_BOLD | (curses.A_REVERSE if i == self.ui else 0))

    def draw_gauge(self):
        """Pitch dial (side view) + yaw compass (top view, N up, like the map)."""
        u, g = self.unit, self.unit.gun
        top, left, w, h = self.vt, 0, 34, 9
        dim = curses.A_DIM
        for r in range(h):
            self.put(top + r, left, " " * w)
        self.put(top, left, "+" + "-" * (w - 2) + "+", dim)
        self.put(top + h - 1, left, "+" + "-" * (w - 2) + "+", dim)
        for r in range(1, h - 1):
            self.put(top + r, left, "|", dim)
            self.put(top + r, left + 16, "|", dim)
            self.put(top + r, left + w - 1, "|", dim)
        self.put(top, left + 2, f" pitch {u.elev:4.0f}d ", curses.A_BOLD)
        self.put(top, left + 18, f" yaw {u.az:4.0f}d ", curses.A_BOLD)

        def slope_char(deg):
            deg %= 180
            return "-" if deg < 22.5 or deg >= 157.5 else "/" if deg < 67.5 else "|" if deg < 112.5 else "\\"

        # pitch: quarter dial, origin bottom-left; '.' marks the allowed arc
        ox, oy, R = left + 2, top + h - 2, 6
        for e in range(0, 91, 5):
            c = ox + int(round(R * math.cos(math.radians(e)) * 2))
            r = oy - int(round(R * math.sin(math.radians(e))))
            ok = g.elev_min <= e <= g.elev_max
            self.put(r, c, "." if ok else " ", curses.color_pair(1) if ok else dim)
        er = math.radians(u.elev)
        for k in (i / 2 for i in range(2, 2 * R)):
            self.put(oy - int(round(k * math.sin(er))), ox + int(round(k * math.cos(er) * 2)),
                     slope_char(u.elev), curses.color_pair(2) | curses.A_BOLD)
        self.put(oy, ox, "o", curses.A_BOLD)

        # yaw: compass, east = 0 deg, counter-clockwise (same as the minimap)
        cx, cy, R = left + 25, top + 4, 3
        for lab, dx, dy in (("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("W", -1, 0)):
            self.put(cy + dy * R, cx + dx * R * 2, lab, dim)
        ar = math.radians(u.az)
        for k in (i / 2 for i in range(2, 2 * R)):
            self.put(cy - int(round(k * math.sin(ar))), cx + int(round(k * math.cos(ar) * 2)),
                     slope_char(u.az), curses.color_pair(2) | curses.A_BOLD)
        self.put(cy - int(round(R * math.sin(ar))), cx + int(round(R * math.cos(ar) * 2)),
                 "*", curses.color_pair(2) | curses.A_BOLD)
        self.put(cy, cx, "o", curses.A_BOLD)

    def draw_graph(self):
        u = self.unit
        idx = self.graph - 1
        unit_s = "m" if idx == 0 else "s"
        gh, gw = min(16, self.vh - 1), min(62, self.W - 2)
        top, left = self.vt + self.vh - gh, self.W - gw
        if self.rotate and gh > self.vh - 15:
            left = 0
        tables = [firing_table(c.velocity, u.shell.drag) for c in u.gun.charges]
        vmax = max(r[idx] for t in tables for r in t) or 1
        # frame
        for r in range(gh):
            self.put(top + r, left, " " * gw)
        self.put(top, left, "+" + "-" * (gw - 2) + "+", curses.A_DIM)
        self.put(top + gh - 1, left, "+" + "-" * (gw - 2) + "+", curses.A_DIM)
        for r in range(1, gh - 1):
            self.put(top + r, left, "|", curses.A_DIM)
            self.put(top + r, left + gw - 1, "|", curses.A_DIM)
        title = " firing table: " + ("range" if idx == 0 else "time of flight") + f" vs elevation - {u.shell.name} "
        self.put(top, left + 2, title, curses.A_BOLD)
        now = table_lookup(tables[u.ci], u.elev, idx)
        self.put(top + 1, left + 2,
                 f"charge {u.charge.name} @ {u.elev:.0f}deg: {now:.0f} {unit_s} (flat ground)  [g]")
        px0, pw = left + 8, gw - 10
        py0, ph = top + 2, gh - 4
        self.put(py0, left + 1, f"{vmax:5.0f}{unit_s}")
        self.put(py0 + ph // 2, left + 1, f"{vmax / 2:5.0f}{unit_s}")
        self.put(py0 + ph - 1, left + 1, f"{0:5.0f}{unit_s}")
        ecol = px0 + int(round(u.elev / 90 * (pw - 1)))
        for r in range(ph):
            self.put(py0 + r, ecol, "|", curses.A_DIM)
        colors = [2, 4, 5, 3, 1]
        for k, tbl in enumerate(tables):
            cur = k == u.ci
            attr = curses.color_pair(colors[k % len(colors)]) | (curses.A_BOLD if cur else curses.A_DIM)
            for c in range(pw):
                e = c / (pw - 1) * 90
                val = table_lookup(tbl, e, idx)
                r = py0 + (ph - 1) - int(round(val / vmax * (ph - 1)))
                self.put(r, px0 + c, str(k + 1) if cur else ".", attr)
        axis = ""
        for c in range(pw):
            e = c / (pw - 1) * 90
            axis += "=" if u.gun.elev_min <= e <= u.gun.elev_max else "-"
        self.put(py0 + ph, px0, axis, curses.A_DIM)
        self.put(py0 + ph, ecol, "^", curses.A_BOLD)
        self.put(py0 + ph, left + 2, "0deg", curses.A_DIM)
        self.put(py0 + ph, px0 + pw - 4, "90", curses.A_DIM)

    def draw_hud(self):
        u, g = self.unit, self.unit.gun
        alive = sum(t.alive for t in self.targets)
        tags = (" [mobile]" if g.mobile else "") + (" [FCS]" if g.prediction else "")
        cam = " freecam" if self.freecam else ""
        self.put(0, 0, f" {'ROTATE' if self.rotate else 'MOVE'}{cam} | unit {self.ui + 1}/{len(self.units)}: "
                 f"{g.name}{tags} | targets left {alive}/{len(self.targets)}  shots {self.shots}",
                 curses.A_REVERSE | curses.A_BOLD)
        if u.shell.fuse == "timed":
            fuse = f"timed {u.fuse_time:.1f}s"
        else:
            fuse = u.shell.fuse
        ready = "READY" if u.cooldown <= 0 else f"reload {u.cooldown:.1f}s"
        self.put(1, 0, f" shell {u.shell.name} ({fuse}, blast {u.shell.blast:.0f}m) | "
                 f"charge {u.charge.name} {u.charge.velocity:.0f}m/s | elev {u.elev:.0f} az {u.az:.0f} | "
                 f"pos {u.x:.0f},{u.y:.0f} | {ready}",
                 curses.color_pair(2) if u.cooldown <= 0 else curses.A_DIM)
        if self.msg_t > 0:
            line = self.msg
        elif g.prediction and getattr(self, "prediction", None):
            _, p = self.prediction
            if p.result == "lost":
                line = "FCS: shell leaves the map"
            else:
                d = math.hypot(p.x - u.x, p.y - u.y)
                line = f"FCS: {p.result} at {d:.0f} m, alt {p.z:.0f} m, tof {p.t:.1f} s"
        else:
            line = f"No fire control: use graph ({self.keys.label('graph')}) and ruler.   {self.keys.label('menu')}: menu  {self.keys.label('help')}: help"
        self.put(self.H - 1, 0, " " + line)

    def box(self, top, left, h, w, title):
        for i in range(h):
            self.put(top + i, left, " " * w, curses.A_REVERSE)
        self.put(top, left + 2, f" {title} ", curses.A_BOLD)

    def draw_menu(self):
        if self.keymenu is not None:
            return self.draw_keymenu()
        rows, info = self.menu_rows(), self.menu_info()
        w = min(self.W - 2, max(66, max(len(l) for l in info) + 4))
        h = len(rows) + len(info) + 6
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, "CONFIGURATION (paused)")
        for i, (label, value, change) in enumerate(rows):
            sel = i == self.menu
            attr = curses.A_BOLD if sel else curses.A_REVERSE
            if not change:
                attr |= curses.A_DIM
            text = f"{'>' if sel else ' '} {label:<13}" + (f"< {value} >" if change else f"  {value}")
            self.put(top + 2 + i, left + 1, text.ljust(w - 2), attr)
        y = top + 3 + len(rows)
        for i, l in enumerate(info):
            self.put(y + i, left + 2, l, curses.A_REVERSE)
        self.put(top + h - 1, left + 2,
                 "Up/Down select  Left/Right change  PgUp/PgDn x5  Enter/Esc close",
                 curses.A_REVERSE | curses.A_DIM)

    def draw_keymenu(self):
        w = min(self.W - 2, 66)
        h = min(self.H - 2, len(ACTIONS) + 5)
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"KEY BINDINGS - {LAYOUTS[self.keys.layout][0]}")
        view = h - 5
        first = max(0, min(self.keymenu - view // 2, len(ACTIONS) - view))
        for i, (action, desc) in enumerate(ACTIONS[first:first + view]):
            idx = first + i
            sel = idx == self.keymenu
            custom = "*" if action in self.keys.overrides else " "
            keys = "<press a key>" if sel and self.capturing else self.keys.label(action)
            text = f"{'>' if sel else ' '} {desc:<30}{custom} {keys}"
            self.put(top + 2 + i, left + 1, text.ljust(w - 2),
                     curses.A_BOLD if sel else curses.A_REVERSE)
        foot = ("Press the new key (Esc cancels)" if self.capturing
                else "Enter rebind  Backspace reset  Esc back   * = custom")
        self.put(top + h - 2, left + 2, foot, curses.A_REVERSE | curses.A_BOLD)
        self.put(top + h - 1, left + 2, f"saved to {os.path.basename(self.keys.path)}",
                 curses.A_REVERSE | curses.A_DIM)

    def draw_help(self):
        items = [(self.keys.label(a), d) for a, d in ACTIONS]
        cw = max(len(k) for k, _ in items) + max(len(d) for _, d in items) + 3
        cols = 2 if 2 * cw + 4 <= self.W and len(items) + len(HELP_NOTES) + 4 > self.H - 2 else 1
        per = math.ceil(len(items) / cols)
        notes_w = max(len(n) for n in HELP_NOTES)
        w = min(self.W, max(cols * cw, notes_w) + 4)
        h = per + len(HELP_NOTES) + 4
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"KEYS - {LAYOUTS[self.keys.layout][0]}")
        kw = max(len(k) for k, _ in items)
        for i, (k, d) in enumerate(items):
            c, r = divmod(i, per)
            self.put(top + 2 + r, left + 2 + c * cw, f"{k:>{kw}}  {d}", curses.A_REVERSE)
        for i, n in enumerate(HELP_NOTES):
            self.put(top + 3 + per + i, left + 2, n, curses.A_REVERSE | curses.A_DIM)

def main(scr):
    curses.curs_set(0)
    curses.set_escdelay(25)
    scr.nodelay(True)
    scr.keypad(True)
    curses.start_color()
    curses.use_default_colors()
    for i, c in enumerate([curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED,
                           curses.COLOR_CYAN, curses.COLOR_MAGENTA], start=1):
        curses.init_pair(i, c, -1)
    game = Game()
    last = time.time()
    while True:
        while (k := scr.getch()) != -1:
            if k == curses.KEY_RESIZE:
                continue
            if not game.key(k):
                return
        now = time.time()
        game.update(min(0.1, now - last))
        last = now
        game.draw(scr)
        time.sleep(0.03)


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(main)
