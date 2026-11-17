"""Key bindings: actions, default layouts and the saved keymap."""
import curses
import json
import os


# ------------------------------------------------------------------ game
# ------------------------------------------------------------------ key bindings
# Every key goes through an action name. Defaults = COMMON_KEYS + the layout,
# and per-action overrides (in-game "Key bindings" menu or the JSON file) win.
ACTIONS = [   # (action, description) - order used by the help and key menu
    ("left",            "turn gun left (one step)"),
    ("right",           "turn gun right (one step)"),
    ("elev_up",         "raise barrel (one step)"),
    ("elev_down",       "lower barrel (one step)"),
    ("elev_up5",        "raise barrel 10 steps"),
    ("elev_down5",      "lower barrel 10 steps"),
    ("step_up",         "bigger aim step / zoom map in"),
    ("step_down",       "finer aim step / zoom map out"),
    ("forward",         "drive forward"),
    ("back",            "drive backward"),
    ("fire",            "fire"),
    ("charge_next",     "next charge"),
    ("charge_prev",     "previous charge"),
    ("shell_next",      "load next shell"),
    ("fuse_down",       "fuse time -0.5 s"),
    ("fuse_up",         "fuse time +0.5 s"),
    ("unit_type",       "change unit type"),
    ("aim_gui",         "precision aiming dial"),
    ("map",             "map: mini > full screen > off"),
    ("graph",           "graph range/tof/firing table/off"),
    ("gauge",           "pitch/yaw gauge"),
    ("freecam",         "free camera"),
    ("new_targets",     "new targets / duel rematch"),
    ("repair",          "repair terrain"),
    ("gun_menu",        "gun settings"),
    ("menu",            "game settings (pause)"),
    ("help",            "help"),
    ("quit",            "quit"),
]


ACTION_IDS = {a for a, _ in ACTIONS}


# locked in a duel once the shot of the turn is in the air
GUN_ACTIONS = {"left", "right", "forward", "back", "elev_up", "elev_down", "elev_up5",
               "elev_down5", "fire", "charge_next", "charge_prev", "shell_next",
               "fuse_down", "fuse_up", "unit_type"}


ENTER_CODES = (10, 13, curses.KEY_ENTER)


COMMON_KEYS = {
    "left": ["left"], "right": ["right"],
    "elev_up": ["up"], "elev_down": ["down"], "elev_up5": ["pgup"], "elev_down5": ["pgdn"],
    "step_up": ["+"], "step_down": ["-"],
    "fire": ["space", "f"], "charge_next": ["c"], "charge_prev": ["C"], "shell_next": ["l"],
    "unit_type": ["tab"], "map": ["m"], "graph": ["g"], "gauge": ["p"], "freecam": ["v"],
    "new_targets": ["n"], "repair": ["r"], "menu": ["esc"], "gun_menu": ["e"], "aim_gui": ["i"],
    "help": ["?", "h"],
}


LAYOUTS = {   # layout id -> (display name, layout-specific keys)
    "azerty": ("AZERTY (ZQSD)", {
        "forward": ["z"], "back": ["s"], "left": ["q"], "right": ["d"],
        "fuse_down": ["("], "fuse_up": [")"], "quit": ["Q"],
    }),
    "wasd": ("QWERTY (WASD)", {
        "forward": ["w"], "back": ["s"], "left": ["a"], "right": ["d"],
        "step_up": ["="], "fuse_down": ["["], "fuse_up": ["]"], "quit": ["q"],
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
KEYS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artillery_keys.json")


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
