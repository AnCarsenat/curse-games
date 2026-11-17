"""Colours. Pairs 1-5 are the classic ones (green, yellow, red, cyan, magenta) set up
in main.py; everything else is an on-demand (fg, bg) pair made by `pair`.

With a 256-colour terminal the terrain gets real materials (grass, rock, snow,
sand, water); with 8 colours everything falls back to the basic palette.
"""
import curses

C = {}            # colour name -> curses colour number (-1 = terminal default)
ENABLED = [True]  # False = monochrome display (bold / dim / reverse only)
_pairs = {}
_next = [6]       # first pair number handed out (1-5 are the classic pairs)

RICH = {
    "sky": -1, "text": 252, "dim": 244, "faint": 238, "accent": 214, "title": 81,
    "good": 114, "bad": 203, "shell": 228, "target": 207,
    "shell_bg": 226, "trail1": 228, "trail2": 214, "trail3": 166, "trail4": 94,
    "bar": 236, "bar_hi": 238, "panel_border": 67, "sel": 24,
    # terrain: a bright surface line, then fills that darken with depth so units,
    # shells and targets stand out against the ground
    "grass": 70, "grass_hi": 70, "dirt": 94, "dirt_dark": 58, "deep": 235,
    "soil1": 94, "soil2": 58, "soil3": 236, "soil4": 234,
    "rock": 243, "rock_hi": 249, "rock1": 244, "rock2": 241, "rock3": 238, "rock4": 235,
    "snow": 255, "sand": 186, "sand_dark": 143, "sand1": 143, "sand2": 101, "sand3": 58, "sand4": 235,
    "red_rock": 173, "red_dark": 131, "red1": 131, "red2": 95, "red3": 237, "red4": 234,
    "scorch": 52, "water": 24, "water_hi": 74, "water2": 18, "water3": 17,
    "map0": 22, "map1": 28, "map2": 64, "map3": 100, "map4": 137, "map5": 244, "map6": 252,
}


def _basic():
    k = curses
    g, y, r, c, m, w, b = (k.COLOR_GREEN, k.COLOR_YELLOW, k.COLOR_RED, k.COLOR_CYAN,
                           k.COLOR_MAGENTA, k.COLOR_WHITE, k.COLOR_BLUE)
    return {
        "sky": -1, "text": w, "dim": w, "faint": w, "accent": y, "title": c,
        "good": g, "bad": r, "shell": y, "target": m,
        "shell_bg": y, "trail1": y, "trail2": y, "trail3": r, "trail4": r,
        "bar": k.COLOR_BLACK, "bar_hi": k.COLOR_BLACK, "panel_border": c, "sel": b,
        "grass": g, "grass_hi": g, "dirt": y, "dirt_dark": y, "deep": k.COLOR_BLACK,
        "soil1": y, "soil2": y, "soil3": k.COLOR_BLACK, "soil4": k.COLOR_BLACK,
        "rock1": w, "rock2": w, "rock3": k.COLOR_BLACK, "rock4": k.COLOR_BLACK,
        "sand1": y, "sand2": y, "sand3": k.COLOR_BLACK, "sand4": k.COLOR_BLACK,
        "red1": r, "red2": r, "red3": k.COLOR_BLACK, "red4": k.COLOR_BLACK,
        "water2": b, "water3": b,
        "rock": w, "rock_hi": w, "snow": w, "sand": y, "sand_dark": y,
        "red_rock": r, "red_dark": r, "scorch": r, "water": b, "water_hi": c,
        "map0": g, "map1": g, "map2": g, "map3": y, "map4": y, "map5": w, "map6": w,
    }


def init():
    C.clear()
    _pairs.clear()
    _next[0] = 6
    C.update(RICH if curses.COLORS >= 256 else _basic())


def rich():
    return C.get("text") == 252


def pair(fg, bg=-1):
    """Attribute for colour numbers fg on bg (made on first use).
    Monochrome: anything on a coloured background becomes reverse video."""
    if not ENABLED[0]:
        return curses.A_REVERSE if bg not in (-1, C.get("sky")) else 0
    key = (fg, bg)
    p = _pairs.get(key)
    if p is None:
        n = _next[0]
        if n >= curses.COLOR_PAIRS:
            return 0
        try:
            curses.init_pair(n, fg, bg)
        except curses.error:
            return 0
        _next[0] += 1
        p = _pairs[key] = curses.color_pair(n)
    return p


def ink(fg, bg="sky", bold=False):
    """Attribute for named colours."""
    attr = pair(C[fg], C[bg]) | (curses.A_BOLD if bold else 0)
    if not ENABLED[0] and fg in ("dim", "faint"):
        attr |= curses.A_DIM
    return attr


_BASE16 = [(0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 238), (205, 0, 205),
           (0, 205, 205), (229, 229, 229), (127, 127, 127), (255, 0, 0), (0, 255, 0),
           (255, 255, 0), (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
_CUBE = [0, 95, 135, 175, 215, 255]


def luminance(c):
    """0..1 brightness of a 256-colour number (-1 = default background, taken as dark)."""
    if c is None or c < 0:
        return 0.0
    if c < 16:
        r, g, b = _BASE16[c]
    elif c < 232:
        c -= 16
        r, g, b = _CUBE[c // 36], _CUBE[c // 6 % 6], _CUBE[c % 6]
    else:
        r = g = b = 8 + 10 * (c - 232)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def readable(fg, bg):
    """fg, or black/white when fg would be hard to see on bg (markers on terrain)."""
    if not rich() or bg in (-1, None) or abs(luminance(fg) - luminance(bg)) >= 0.3:
        return fg
    return 16 if luminance(bg) > 0.45 else 231


def classic(n):
    """One of the five classic pairs from main.py (0 when colour is off)."""
    return curses.color_pair(n) if ENABLED[0] else 0
