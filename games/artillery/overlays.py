"""Modal boxes: settings menus, key bindings, help, title, duel screens."""
import curses
import math
import os

from .config import MODES
from .keys import ACTIONS, LAYOUTS
from .world import WORLD_TYPES


HELP_NOTES = [
    "Arrows aim (left/right = yaw, up/down = pitch) by the step shown in the HUD;",
    "  +/- change the step (10 / 1 / 0.1 / 0.01 deg). Letters drive and turn.",
    "The view is a side slice of the world along the gun heading.",
    "Map: the line shows where the gun points; + = flat-ground range estimate,",
    "  X = computed impact (FCS / tank sight). Full map: pan, +/- zoom, Home fits.",
    "FCS guns show the whole arc, the tank sight only its end; both ignore wind.",
    "Firing table (graph 3): elevation / time of flight per range. Set timed",
    "  fuses to the time of flight. Rebind keys in game settings > Key bindings.",
    "Duel: one shot per turn, hand over the keyboard, wind rerolls each turn.",
    "New world each game; pick its type (Mixed, Islands, Canyons...) on the title",
    "  screen or in game settings > World type. Lakes (~): no driving or",
    "  craters in water. Wider views are flatter; Relief (game settings) scales height.",
]


class OverlaysMixin:
    def box(self, top, left, h, w, title):
        for i in range(h):
            self.put(top + i, left, " " * w, curses.A_REVERSE)
        self.put(top, left + 2, f" {title} ", curses.A_BOLD)

    def draw_lines(self, title, lines, foot, color=0):
        w = min(self.W - 2, max(len(l) for l in lines + [foot, title]) + 6)
        h = len(lines) + 5
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, title)
        for i, l in enumerate(lines):
            self.put(top + 2 + i, left + 3, l, curses.A_REVERSE | (curses.A_BOLD if i == 0 else 0))
        self.put(top + h - 1, left + 2, foot, curses.A_REVERSE | curses.A_DIM)
        if color:
            self.put(top, left + 2, f" {title} ", curses.A_BOLD | curses.color_pair(color))

    def draw_handover(self):
        u = self.unit
        lines = [f"{u.name.upper()} - take the keyboard", ""]
        if self.report:
            lines += [f"Last shot: {self.report}", ""]
        lines.append(f"This turn: {self.wind_text()} ('w' on the yaw gauge)   Your HP: {u.hp}")
        self.draw_lines("DUEL", lines, f"Enter / {self.keys.label('fire')}: start turn", u.color)

    def draw_winner(self):
        self.draw_lines("GAME OVER", [self.winner, "", f"Last shot: {self.report}"],
                        f"{self.keys.label('new_targets')}: rematch   {self.keys.label('menu')}: menu"
                        f"   {self.keys.label('quit')}: quit")

    def draw_title(self):
        lines = ["Choose a game mode:", ""]
        for i, (_, name, desc) in enumerate(MODES):
            lines.append(f"{'>' if i == self.title else ' '} {i + 1}. {name:<8} {desc}")
        _, wname, wdesc, _, _ = WORLD_TYPES[self.world_type]
        lines += ["", f"World:  < {wname} >  {wdesc}"]
        w = min(self.W - 2, max(len(l) for l in lines) + 6)
        h = len(lines) + 5
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, "ARTILLERY")
        for i, l in enumerate(lines):
            sel = i - 2 == self.title
            self.put(top + 2 + i, left + 3, l.ljust(w - 6), curses.A_BOLD if sel else curses.A_REVERSE)
        self.put(top + len(lines) + 1, left + 3, f"World:  < {wname} >", curses.A_BOLD)
        self.put(top + h - 1, left + 2, "Up/Down or 1-2 mode  Left/Right world  Enter start  Esc cancel",
                 curses.A_REVERSE | curses.A_DIM)

    def draw_menu(self):
        if self.keymenu is not None:
            return self.draw_keymenu()
        rows, info = self.menu_rows(), self.menu_info()
        w = min(self.W - 2, max(66, max(len(l) for l in info) + 4))
        h = len(rows) + len(info) + 6
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"{'GUN' if self.menu_page == 'gun' else 'GAME'} SETTINGS (paused)")
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
                 "Up/Down select  Left/Right change  PgUp/PgDn x5  Tab page  Enter/Esc close",
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
