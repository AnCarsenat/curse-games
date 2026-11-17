"""Curses setup and the main loop."""
import curses
import locale
import time

from .game import Game


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
    frame = 1 / 30
    last = time.perf_counter()
    next_frame = last
    while True:
        # wait for a key or the next frame, whichever comes first, then drain input
        scr.timeout(max(0, int((next_frame - time.perf_counter()) * 1000)))
        handled = False
        k = scr.getch()
        while k != -1:
            if k != curses.KEY_RESIZE:
                if not game.key(k):
                    return
                handled = True
            scr.timeout(0)
            k = scr.getch()
        now = time.perf_counter()
        if handled or now >= next_frame:
            game.update(min(0.1, now - last))
            last = now
            game.draw(scr)
            next_frame = now + frame


def run():
    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(main)
