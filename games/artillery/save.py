"""Save and continue. The game is saved when you quit (q / Ctrl+C) and the title
screen offers "Continue last game" next time. Shells in flight are not saved."""
import json
import os
import time

from . import colors, world
from .content import GUNS
from .entities import Target, Unit

SAVE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "artillery_save.json")
VERSION = 1
SETTINGS = ("span_i", "relief_i", "world_type", "aim_step", "gauge", "graph", "wind_on", "display",
            "flat_next")
UNIT_FIELDS = ("x", "y", "az", "elev", "ci", "si", "fuse_time", "hp", "fuel", "name", "color", "flip")


def read(path=SAVE_FILE):
    """The saved data, or None if there is no usable save."""
    try:
        with open(path) as f:
            data = json.load(f)
        return data if data.get("version") == VERSION else None
    except (OSError, ValueError, AttributeError):
        return None


def describe(data):
    """One line for the title screen: mode, world, progress, when."""
    mode = ("Duel" if data["mode"] == "duel" else "Sandbox") + (" 2D" if data.get("flat") else "")
    wname = world.WORLD_TYPES[data["world"]][1]
    when = time.strftime("%d %b %H:%M", time.localtime(data["time"]))
    if data["mode"] == "duel":
        hp = " vs ".join(str(u["hp"]) for u in data["units"])
        what = f"HP {hp}"
    else:
        alive = sum(1 for t in data["targets"] if t[2])
        what = f"{alive}/{len(data['targets'])} targets left, {data['shots']} shots"
    return f"{mode} · {wname} · {what} · {when}"


def save(g, path=SAVE_FILE):
    data = {
        "version": VERSION, "time": time.time(),
        "mode": g.mode, "seed": g.seed, "world": g.world_now, "flat": g.flat,
        "craters": {f"{cx},{cy}": c for (cx, cy), c in world._chunks.items()},
        "units": [dict({k: getattr(u, k) for k in UNIT_FIELDS}, gun=GUNS.index(u.gun))
                  for u in g.units],
        "ui": g.ui,
        "targets": [[t.x, t.y, t.alive] for t in g.targets],
        "wind": list(g.wind), "shots": g.shots,
        "explored": [list(c) for c in g.explored],
        "turn_fired": g.turn_fired, "winner": g.winner, "report": g.report,
        "settings": {k: getattr(g, k) for k in SETTINGS},
    }
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def load(g, data):
    """Restore a game from `read()` data."""
    for k, v in data["settings"].items():
        if k in SETTINGS:
            setattr(g, k, v)
    colors.ENABLED[0] = g.display != "mono"
    g.mode, g.seed = data["mode"], data["seed"]
    g.flat = data.get("flat", False)
    world.new_world(g.seed, data["world"])
    g.world_now = data["world"]
    for key, c in data["craters"].items():
        cx, cy = (int(v) for v in key.split(","))
        world._chunks[(cx, cy)] = c
    world.terrain_version[0] += 1
    g.map_cache = {}
    g._frame_key = None
    if g.map_mode == 2:
        g.map_mode = 1
    g.units = []
    for d in data["units"]:
        gun = GUNS[d["gun"]]
        u = Unit(gun, d["x"], d["y"], d["name"], d["color"])
        for k in UNIT_FIELDS:
            setattr(u, k, d[k])
        u.ci = min(u.ci, len(gun.charges) - 1)
        u.si = min(u.si, len(gun.shells) - 1)
        g.units.append(u)
    g.ui = min(data["ui"], len(g.units) - 1)
    g.targets = [Target(x, y, alive) for x, y, alive in data["targets"]]
    g.wind = tuple(data["wind"])
    g.shots = data["shots"]
    g.explored = {tuple(c) for c in data["explored"]}
    g.projectiles, g.explosions = [], []
    g.aim = g.entry = None
    g.freecam, g.input_mode = False, "move"
    g.turn_fired, g.winner, g.report = data["turn_fired"], data["winner"], data["report"]
    g.handover = g.mode == "duel" and not g.winner and not g.turn_fired
    if g.winner:
        g.say(f"{g.winner}   {g.keys.label('new_targets')}: rematch", 1e9)
    else:
        g.say("Welcome back", 2)
