"""Modal boxes: settings menus, key bindings, help, title, duel screens."""
import curses
import math
import os

from . import colors
from .colors import C, pair
from .keys import ACTIONS, LAYOUTS
from .world import WORLD_TYPES


HELP_NOTES = [
    "Tab switches what ZQSD do: MOVE (drive/turn), AIM (pitch/yaw, , ; step),",
    "  CAMERA (pan the side view: Q/D left/right, Z/S up/down). Arrows always aim.",
    "Two small maps: the world from above, and the slice - the whole firing line",
    "  side-on, with the part the main view shows bracketed underneath.",
    "Arrows aim (left/right = yaw, up/down = pitch) by the step shown in the HUD;",
    "  hold a key to speed up. +/- change the step (10 / 1 / 0.1 / 0.01 deg).",
    "Type a number (or open the dial) to set pitch/yaw exactly: 42.5 Enter.",
    "The view is a side slice of the world along the gun heading.",
    "Map: the line shows where the gun points; + = flat-ground range estimate,",
    "  X = computed impact (FCS / tank sight). Full map: pan, +/- zoom, Home fits.",
    "FCS guns show the whole arc, the tank sight only its end; both ignore wind.",
    "Targets: magenta T = within blast of your firing line (right range hits it),",
    "  dim t = out of reach on this heading, red T = computed shot will hit (FCS/sight).",
    "Dimensions (game settings): 2D puts everything on the side view - no yaw,",
    "  left/right face west/east, wind blows along the line, only the slice map.",
    "Firing table (graph 3): elevation / time of flight per range. Set timed",
    "  fuses to the time of flight. Rebind keys in game settings > Key bindings.",
    "Duel: one shot per turn, hand over the keyboard, wind rerolls each turn.",
    "New world each game; pick its type (Mixed, Islands, Canyons...) on the title",
    "  screen or in game settings > World type. Lakes (~): no driving or",
    "  craters in water. Wider views are flatter; Relief (game settings) scales height.",
]


LOGO = [
    "▄▀█ █▀█ ▀█▀ █ █   █   █▀▀ █▀█ █▄█",
    "█▀█ █▀▄  █  █ █▄▄ █▄▄ ██▄ █▀▄  █ ",
]


class OverlaysMixin:
    # text attributes inside modal boxes
    @property
    def t_text(self):
        return colors.ink("text")

    @property
    def t_dim(self):
        return colors.ink("dim")

    @property
    def t_sel(self):
        return pair(C["text"], C["sel"]) | curses.A_BOLD

    def box(self, top, left, h, w, title, color=None):
        """Modal box: cleared inside, rounded border, title in the top edge."""
        self.frame(top, left, h, w)
        if title:
            attr = (pair(C["deep"], color) if color is not None else colors.ink("accent")) | curses.A_BOLD
            self.put(top, left + 2, f" {title} ", attr)

    def draw_lines(self, title, lines, foot, color=None):
        w = min(self.W - 2, max(len(l) for l in lines + [foot, title]) + 6)
        h = len(lines) + 5
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, title, color)
        for i, l in enumerate(lines):
            self.put(top + 2 + i, left + 3, l, self.t_text | (curses.A_BOLD if i == 0 else 0))
        self.put(top + h - 2, left + 3, foot, colors.ink("accent"))

    def draw_handover(self):
        u = self.unit
        lines = [f"{u.name.upper()} - take the keyboard", ""]
        if self.report:
            lines += [f"Last shot: {self.report}", ""]
        lines.append(f"This turn: {self.wind_text()} ('w' on the yaw gauge)   Your HP: {u.hp}")
        self.draw_lines("DUEL", lines, f"Enter / {self.hint('fire')}: start turn", self.unit_fg(u))

    def draw_winner(self):
        self.draw_lines("GAME OVER", [self.winner, "", f"Last shot: {self.report}"],
                        f"{self.hint('new_targets')} rematch   {self.hint('menu')} menu"
                        f"   {self.hint('quit')} quit", C["accent"])

    def draw_title(self):
        _, wname, wdesc, _, _ = WORLD_TYPES[self.world_type]
        rows = [f"{i + 1}  {name:<9} {desc}" for i, (_, name, desc) in enumerate(self.title_items())]
        w = min(self.W - 2, max(max(len(r) for r in rows), len(wdesc) + 14, len(LOGO[0])) + 10)
        h = len(rows) + 12
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, "")
        for i, l in enumerate(LOGO):
            self.put(top + 1 + i, left + (w - len(l)) // 2, l, colors.ink("accent", bold=True))
        self.put(top + 3, left + (w - 24) // 2, "terminal artillery range", self.t_dim)
        self.put(top + 5, left + 3, "Play", self.t_dim)
        for i, r in enumerate(rows):
            sel = i == self.title
            self.put(top + 6 + i, left + 3, (" ▶ " if sel else "   ") + r.ljust(w - 9),
                     self.t_sel if sel else self.t_text)
        y = top + 7 + len(rows)
        self.put(y, left + 3, "World", self.t_dim)
        self.put(y, left + 9, "(for new games)", self.t_dim)
        self.put(y + 1, left + 3, f"  ◀ {wname} ▶", colors.ink("title", bold=True))
        self.put(y + 1, left + 9 + len(wname), wdesc, self.t_dim)
        self.hints(top + h - 2, left + 3, [("↑↓", "mode"), ("←→", "world"), ("Enter", "start"),
                                           ("Esc", "cancel")], limit=left + w - 1)

    def draw_menu(self):
        if self.keymenu is not None:
            return self.draw_keymenu()
        rows, info = self.menu_rows(), self.menu_info()
        w = min(self.W - 2, max(70, max(len(l) for l in info) + 6))
        h = len(rows) + len(info) + 7
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"{'GUN' if self.menu_page == 'gun' else 'GAME'} SETTINGS · paused")
        # page tabs
        for i, (page, name) in enumerate((("game", "Game"), ("gun", "Gun"))):
            self.put(top + 1, left + w - 18 + i * 8, f" {name} ",
                     self.t_sel if page == self.menu_page else self.t_dim)
        for i, (label, value, change) in enumerate(rows):
            sel = i == self.menu
            text = f"{' ▶' if sel else '  '} {label:<13}" + (f"◀ {value} ▶" if change else f"  {value}")
            attr = self.t_sel if sel else (self.t_text if change else self.t_dim)
            self.put(top + 2 + i, left + 1, text.ljust(w - 2), attr)
        y = top + 3 + len(rows)
        self.put(y, left + 1, "─" * (w - 2), colors.ink("faint"))
        for i, l in enumerate(info):
            self.put(y + 1 + i, left + 3, l, self.t_dim)
        self.hints(top + h - 2, left + 3, [("↑↓", "select"), ("←→", "change"), ("PgUp/PgDn", "x5"),
                                           ("Tab", "page"), ("Enter/Esc", "close")], limit=left + w - 1)

    def draw_keymenu(self):
        w = min(self.W - 2, 70)
        h = min(self.H - 2, len(ACTIONS) + 6)
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"KEY BINDINGS · {LAYOUTS[self.keys.layout][0]}")
        view = h - 6
        first = max(0, min(self.keymenu - view // 2, len(ACTIONS) - view))
        for i, (action, desc) in enumerate(ACTIONS[first:first + view]):
            idx = first + i
            sel = idx == self.keymenu
            custom = "*" if action in self.keys.overrides else " "
            keys = "<press a key>" if sel and self.capturing else self.keys.label(action)
            text = f"{' ▶' if sel else '  '} {desc:<32}{custom} {keys}"
            self.put(top + 1 + i, left + 1, text.ljust(w - 2), self.t_sel if sel else self.t_text)
        foot = ("Press the new key (Esc cancels)" if self.capturing
                else "Enter rebind  Backspace reset  Esc back   * = custom")
        self.put(top + h - 3, left + 3, foot, colors.ink("accent", bold=True))
        self.put(top + h - 2, left + 3, f"saved to {os.path.basename(self.keys.path)}", self.t_dim)

    def draw_help(self):
        items = [(self.keys.label(a), d) for a, d in ACTIONS]
        cw = max(len(k) for k, _ in items) + max(len(d) for _, d in items) + 4
        cols = 2 if 2 * cw + 6 <= self.W and len(items) + len(HELP_NOTES) + 5 > self.H - 2 else 1
        per = math.ceil(len(items) / cols)
        notes_w = max(len(n) for n in HELP_NOTES)
        w = min(self.W, max(cols * cw, notes_w) + 6)
        h = min(self.H, per + len(HELP_NOTES) + 5)
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"KEYS · {LAYOUTS[self.keys.layout][0]} · any key closes")
        kw = max(len(k) for k, _ in items)
        for i, (k, d) in enumerate(items):
            c, r = divmod(i, per)
            x = left + 3 + c * cw
            self.put(top + 1 + r, x, f"{k:>{kw}}", colors.ink("accent", bold=True))
            self.put(top + 1 + r, x + kw + 2, d, self.t_text)
        self.put(top + 2 + per, left + 1, "─" * (w - 2), colors.ink("faint"))
        for i, n in enumerate(HELP_NOTES):
            self.put(top + 3 + per + i, left + 3, n, self.t_dim)
