#!/usr/bin/env python3
"""curse-games launcher.

Run:  python3 launcher.py

  up/down or j/k   move          Enter   play
  /                search        1-9     quick launch
  Esc              clear search, or quit   q  quit

Games are found automatically in games/: a package with __main__.py
(run as `python3 -m name`) or a single .py file. The first line of the
docstring ("name - short description") is shown in the list.
"""
import ast
import curses
import locale
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(ROOT, "games")
ENTER = (10, 13, curses.KEY_ENTER)
ESC = 27


def docstring(path):
    try:
        with open(path, encoding="utf-8") as f:
            return ast.get_docstring(ast.parse(f.read())) or ""
    except (OSError, SyntaxError, ValueError):
        return ""


def discover():
    games = []
    for entry in sorted(os.listdir(GAMES)):
        path = os.path.join(GAMES, entry)
        if entry.startswith((".", "_")):
            continue
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "__main__.py")):
            doc = docstring(os.path.join(path, "__init__.py")) or docstring(
                os.path.join(path, "__main__.py"))
            cmd = [sys.executable, "-m", entry]
        elif entry.endswith(".py"):
            doc = docstring(path)
            cmd = [sys.executable, entry]
            entry = entry[:-3]
        else:
            continue
        first = doc.strip().splitlines()[0] if doc.strip() else ""
        desc = first.split(" - ", 1)[1] if " - " in first else first
        games.append({"name": entry.replace("_", " "), "desc": desc, "doc": doc, "cmd": cmd})
    return games


def score(game, query):
    """Higher is better, None = no match. Every word must appear (or be a
    subsequence of the name, so 'smt' finds 'smoll tanks')."""
    if not query:
        return 0
    name, hay = game["name"].lower(), (game["name"] + " " + game["desc"]).lower()
    total = 0
    for word in query.lower().split():
        if name.startswith(word):
            total += 30
        elif word in name:
            total += 20
        elif word in hay:
            total += 10
        else:
            it = iter(name.replace(" ", ""))
            if all(ch in it for ch in word):
                total += 5
            else:
                return None
    return total


def filtered(games, query):
    hits = [(score(g, query), i, g) for i, g in enumerate(games)]
    hits = [h for h in hits if h[0] is not None]
    hits.sort(key=lambda h: (-h[0], h[1]))
    return [g for _, _, g in hits]


def put(scr, y, x, text, attr=0):
    h, w = scr.getmaxyx()
    if 0 <= y < h and 0 <= x < w:
        try:
            scr.addstr(y, x, text[: w - x - (1 if y == h - 1 else 0)], attr)
        except curses.error:
            pass


LOGO = [
    "┏━╸╻ ╻┏━┓┏━┓┏━╸   ┏━╸┏━┓┏┳┓┏━╸┏━┓",
    "┃  ┃ ┃┣┳┛┗━┓┣╸    ┃╺┓┣━┫┃┃┃┣╸ ┗━┓",
    "┗━╸┗━┛╹┗╸┗━┛┗━╸   ┗━┛╹ ╹╹ ╹┗━╸┗━┛",
]


def pick(scr, state):
    """Show the list; return the chosen game, or None to quit."""
    curses.curs_set(0)
    curses.set_escdelay(25)
    scr.keypad(True)
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    for i, c in enumerate([curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_GREEN,
                           curses.COLOR_RED, curses.COLOR_WHITE], start=1):
        curses.init_pair(i, c, -1)
    CYAN, YELLOW, GREEN, RED, DIM = (curses.color_pair(i) for i in range(1, 6))

    games = discover()
    while True:
        shown = filtered(games, state["query"])
        state["sel"] = max(0, min(state["sel"], len(shown) - 1))
        scr.erase()
        h, w = scr.getmaxyx()
        for i, line in enumerate(LOGO):
            put(scr, 1 + i, max(0, (w - len(LOGO[0])) // 2), line, CYAN | curses.A_BOLD)
        y = 5
        if state["searching"] or state["query"]:
            cur = "█" if state["searching"] else ""
            put(scr, y, 2, "/", YELLOW | curses.A_BOLD)
            put(scr, y, 4, state["query"] + cur, curses.A_BOLD)
            put(scr, y, max(4, w - 16), f"{len(shown)}/{len(games)} games", DIM)
        else:
            put(scr, y, 2, f"{len(games)} games    / to search", DIM)
        y += 2
        list_h = max(1, h - y - 9)
        top = max(0, state["sel"] - list_h + 1)
        if not shown:
            put(scr, y, 4, "no game matches", RED)
        for row, g in enumerate(shown[top: top + list_h]):
            i = top + row
            selected = i == state["sel"]
            num = f"{i + 1}" if i < 9 and not state["searching"] else " "
            line = f" {num} {g['name']:<18} {g['desc']}"
            put(scr, y + row, 2, line.ljust(w - 4)[: w - 4],
                (curses.A_REVERSE | GREEN | curses.A_BOLD) if selected else 0)
        if shown:
            doc = shown[state["sel"]]["doc"].strip().splitlines()[1:]
            doc = [l for l in doc if l.strip()][:6]
            for i, l in enumerate(doc):
                put(scr, h - 8 + i, 4, l, DIM)
        if state["msg"]:
            put(scr, h - 2, 2, state["msg"], RED)
        keys = ("type to filter  Enter play  Esc clear" if state["searching"]
                else "↑↓/ZS move  Enter play  / search  1-9 quick  q/Esc quit")
        put(scr, h - 1, 2, keys, DIM)
        scr.refresh()

        k = scr.get_wch()
        state["msg"] = ""
        if k == curses.KEY_RESIZE:
            continue
        if k in (curses.KEY_UP,) or (not state["searching"] and k in ("k", "z")):
            state["sel"] -= 1
        elif k in (curses.KEY_DOWN,) or (not state["searching"] and k in ("j", "s")):
            state["sel"] += 1
        elif k in (curses.KEY_HOME,):
            state["sel"] = 0
        elif k in (curses.KEY_END,):
            state["sel"] = len(shown) - 1
        elif k in ENTER or k in ("\n", "\r"):
            if shown:
                state["searching"] = False
                return shown[state["sel"]]
        elif k == chr(ESC) or k == ESC:
            if not (state["searching"] or state["query"]):
                return None
            state["query"], state["searching"], state["sel"] = "", False, 0
        elif state["searching"]:
            if k in (curses.KEY_BACKSPACE, "\x7f", "\b", 127, 8):
                if state["query"]:
                    state["query"] = state["query"][:-1]
                else:
                    state["searching"] = False
            elif isinstance(k, str) and k.isprintable():
                state["query"] += k
                state["sel"] = 0
        elif k == "/":
            state["searching"] = True
        elif k in ("q", "x"):
            return None
        elif isinstance(k, str) and k.isdigit() and k != "0":
            i = int(k) - 1
            if i < len(shown):
                return shown[i]


def main():
    locale.setlocale(locale.LC_ALL, "")
    state = {"query": "", "searching": False, "sel": 0, "msg": ""}
    while True:
        try:
            game = curses.wrapper(pick, state)
        except KeyboardInterrupt:
            return
        if game is None:
            return
        try:
            code = subprocess.call(game["cmd"], cwd=GAMES)
        except KeyboardInterrupt:
            code = 0
        except OSError as e:
            code, state["msg"] = 1, f"could not start {game['name']}: {e}"
            continue
        if code not in (0, -2):
            state["msg"] = f"{game['name']} exited with code {code}"


if __name__ == "__main__":
    main()
