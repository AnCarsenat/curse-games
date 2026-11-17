"""Panels drawn over the view: maps, gauge, aiming dial, graphs/tables and the HUD."""
import curses
import math

from . import colors
from .colors import C, pair
from .config import AIM_STEPS, SEA, VIEW_SPANS
from .world import WORLD_TYPES, deform, height, raw_height, shade_level, terrain_version
from .physics import firing_table, high_angle, low_angle, slope_char, table_lookup


class PanelsMixin:
    def impact_estimate(self):
        """(x, y, exact): computed impact for FCS/sight guns, else flat-ground range."""
        u = self.unit
        if self.pred and self.pred[1].result != "lost":
            p = self.pred[1]
            return p.x, p.y, True
        r = table_lookup(firing_table(u.charge.velocity, u.shell.drag), u.elev, 0)
        a = math.radians(u.az)
        return u.x + r * math.cos(a), u.y + r * math.sin(a), False

    def frame(self, top, left, h, w, title="", foot="", fill=True):
        """Rounded panel border; clears the inside unless fill is False."""
        border = colors.ink("panel_border")
        self.put(top, left, "╭" + "─" * (w - 2) + "╮", border)
        for r in range(1, h - 1):
            if fill:
                self.put(top + r, left, "│" + " " * (w - 2) + "│", border)
            else:
                self.put(top + r, left, "│", border)
                self.put(top + r, left + w - 1, "│", border)
        self.put(top + h - 1, left, "╰" + "─" * (w - 2) + "╯", border)
        if title:
            self.put(top, left + 2, f" {title} ", colors.ink("accent", bold=True))
        if foot:
            self.put(top + h - 1, left + 2, f" {foot} ", colors.ink("dim"))

    def draw_map(self, top, left, mw, mh, x0, ytop, mpc, title, foot=""):
        """Top-down map, north up. mpc = metres per column (a row is 2 columns tall)."""
        # Cells are aligned to a world grid of mpc x 2*mpc metres, so panning reuses
        # every cell already computed; only newly exposed ones are sampled.
        i0, j0 = math.floor(x0 / mpc), math.floor(ytop / (2 * mpc))
        mk = round(mpc, 5)
        key = (mw, mh, i0, j0, mk)
        rows = self.map_cache.get(key)
        if rows is None:
            cells = self.map_cache.get("cells")
            if len(self.map_cache) > 10 or cells is None or len(cells) > 400000:
                self.map_cache = {"cells": cells if cells is not None and len(cells) <= 400000 else {}}
                cells = self.map_cache["cells"]
            rows = []
            for j in range(mh):
                jj = j0 - j
                y = (jj + 0.5) * 2 * mpc
                line = []
                for i in range(i0, i0 + mw):
                    ch = cells.get((mk, i, jj))
                    if ch is None:
                        x = (i + 0.5) * mpc
                        # straight from the noise (no chunk generation), detail matched to zoom
                        h = raw_height(x, y, mpc) + deform(x, y)
                        ch = cells[(mk, i, jj)] = "~" if h < SEA else str(shade_level(h))
                    line.append(ch)
                rows.append("".join(line))
            self.map_cache[key] = rows
        # '~' water, '0'..'6' height bands: solid colour cells, or shading characters
        blocks = self.display == "blocks"
        band_col = {"~": C["water"], **{str(i): C[f"map{i}"] for i in range(7)}}
        cell_bg = band_col if blocks else dict.fromkeys(band_col, C["sky"])
        shade = {"~": "~", **{str(i): " `,:;=%#"[1 + i] for i in range(7)}}
        self.frame(top, left, mh + 2, mw + 2, title, foot, fill=False)
        for j, row in enumerate(rows):
            c = 0
            while c < mw:
                ch = row[c]
                e = c + 1
                while e < mw and row[e] == ch:
                    e += 1
                if blocks:
                    self.put(top + 1 + j, left + 1 + c, " " * (e - c), pair(C["text"], cell_bg[ch]))
                else:
                    fg = C["water_hi"] if ch == "~" else band_col[ch]
                    self.put(top + 1 + j, left + 1 + c, shade[ch] * (e - c), pair(fg))
                c = e

        def plot(x, y, ch, fg, extra=curses.A_BOLD):
            c = left + 1 + math.floor(x / mpc) - i0
            r = top + 1 + j0 - math.floor(y / (2 * mpc))
            if left < c <= left + mw and top < r <= top + mh:
                bg = cell_bg[rows[r - top - 1][c - left - 1]]
                self.put(r, c, ch, pair(colors.readable(fg, bg), bg) | extra)
                return c, r
            return None

        # aim line: from the gun to where the shell should land
        u = self.unit
        ix, iy, exact = self.impact_estimate()
        n = max(2, min(4 * mw, int(math.hypot(ix - u.x, iy - u.y) / mpc * 1.5)))
        for k in range(1, n):
            plot(u.x + (ix - u.x) * k / n, u.y + (iy - u.y) * k / n, "·", C["title"])
        for t in self.targets:
            state = self.target_state(t)
            if state == "hit":
                c = left + 1 + math.floor(t.x / mpc) - i0
                r = top + 1 + j0 - math.floor(t.y / (2 * mpc))
                if left < c <= left + mw and top < r <= top + mh:
                    self.put(r, c, "T", pair(231, C["bad"]) | curses.A_BOLD)
            elif state == "line":
                c = left + 1 + math.floor(t.x / mpc) - i0
                r = top + 1 + j0 - math.floor(t.y / (2 * mpc))
                if left < c <= left + mw and top < r <= top + mh:
                    self.put(r, c, "T", pair(C["deep"], C["target"]) | curses.A_BOLD)
            else:
                plot(t.x, t.y, "x" if state == "dead" else "t", C["dim"], 0)
        plot(ix, iy, "X" if exact else "+", C["shell"])
        for p in self.projectiles:
            for pt in p.trail[::8]:
                plot(pt[0], pt[1], "·", C["trail2"])
            c = left + 1 + math.floor(p.x / mpc) - i0
            r = top + 1 + j0 - math.floor(p.y / (2 * mpc))
            if left < c <= left + mw and top < r <= top + mh:
                self.put(r, c, "●", pair(C["deep"], C["shell_bg"]) | curses.A_BOLD)
        for e in self.explosions:
            plot(e.pos[0], e.pos[1], "*", C["bad"])
        # units, each with a short barrel pointing along its heading
        for i, un in enumerate(self.units):
            fg = self.unit_fg(un)
            pos = plot(un.x, un.y, un.gun.char, fg,
                       curses.A_BOLD | (curses.A_REVERSE if i == self.ui else 0))
            if not pos:
                continue
            a = math.radians(un.az)
            for k in (1, 2):
                plot(un.x + 2 * k * mpc * math.cos(a), un.y + 2 * k * mpc * math.sin(a),
                     slope_char(un.az), fg)

    def draw_minimap(self):
        mw, mh = 26, 13
        x0, y0, side = self.map_region()
        mpc = side / mw
        self.draw_map(self.vt, self.W - mw - 2, mw, mh, x0, y0 + side, mpc,
                      f"map {side / 1000:.1f} km", f"{self.hint('map')} full")

    def slice_line(self):
        """(x0, y0, heading, length) of the slice map: the whole firing line, from a
        little behind the gun to past the longest range of the current gun and shell."""
        u = self.unit
        rmax = max(max(r for r, _ in firing_table(c.velocity, u.shell.drag)) for c in u.gun.charges)
        L = max(VIEW_SPANS[self.span_i], rmax * 1.15)
        if self.flat:                       # east stays on the right
            east = math.cos(math.radians(u.az)) >= 0
            return u.x - (0.06 if east else 0.94) * L, u.y, 0.0, L
        a = math.radians(u.az)
        return u.x - 0.06 * L * math.cos(a), u.y - 0.06 * L * math.sin(a), u.az, L

    def draw_slicemap(self, top):
        """Side profile of the whole firing line, with the part the view shows marked."""
        from .view import MATERIALS, material
        mw, mh = 26, 6
        left = self.W - mw - 2
        x0, y0, heading, L = self.slice_line()
        ca, sa = math.cos(math.radians(heading)), math.sin(math.radians(heading))
        key = (x0, y0, heading, L, terrain_version[0], self.display, self.world_now)
        if getattr(self, "_slice_key", None) != key:
            hs = []
            for i in range(mw):
                s = (i + 0.5) / mw * L
                x, y = x0 + s * ca, y0 + s * sa
                hs.append(raw_height(x, y, L / mw) + deform(x, y))
            lo = min(min(hs), SEA) - 5
            hi = max(max(hs), SEA, lo + 50)
            self._slice_key, self._slice = key, (hs, lo, hi)
        hs, lo, hi = self._slice
        halves = mh * 2

        def half_row(z):                    # 0 = top half of the first row
            return int(round((hi - z) / (hi - lo) * (halves - 1)))

        def col_of(x, y):
            return int(((x - x0) * ca + (y - y0) * sa) / L * mw)

        self.frame(top, left, mh + 2, mw + 2, f"slice {L / 1000:.1f} km", fill=False)
        sky, water = C["sky"], C["water"]
        world_id = WORLD_TYPES[self.world_now][0]
        blocks = self.display == "blocks"
        sea = half_row(SEA)
        cells = [[(" ", C["text"], sky)] * mw for _ in range(mh)]
        for i, h in enumerate(hs):
            mat_top, fill = MATERIALS["sand" if h < SEA else material(world_id, h)]
            top_c, fill_c = C[mat_top], C[fill[1]]
            g = half_row(h)
            for r in range(mh):
                upper, lower = 2 * r, 2 * r + 1
                def at(hr):
                    if hr > g:
                        return fill_c
                    if hr == g:
                        return top_c
                    return water if h < SEA and hr >= sea else sky
                a, b = at(upper), at(lower)
                if blocks:
                    cells[r][i] = ("▀", a, b) if a != b else (" ", C["text"], a)
                else:
                    ch = (":" if upper > g else "#" if g in (upper, lower) else
                          "~" if h < SEA and sea in (upper, lower) else " ")
                    fg = fill_c if ch == ":" else top_c if ch == "#" else C["water_hi"]
                    cells[r][i] = (ch, fg, sky)
        for r, row in enumerate(cells):
            c = 0
            while c < mw:
                e = c + 1
                while e < mw and row[e] == row[c]:
                    e += 1
                ch, fg, bg = row[c]
                self.put(top + 1 + r, left + 1 + c, ch * (e - c), pair(fg, bg))
                c = e

        def mark(x, y, z, ch, attr):
            c = col_of(x, y)
            if 0 <= c < mw:
                r = max(0, min(mh - 1, half_row(z) // 2))
                self.put(top + 1 + r, left + 1 + c, ch, attr)

        u = self.unit
        for t in self.targets:
            state = self.target_state(t)
            if state in ("hit", "line"):
                mark(t.x, t.y, t.z, "T", pair(231, C["bad"]) | curses.A_BOLD if state == "hit"
                     else pair(C["deep"], C["target"]) | curses.A_BOLD)
        for i, un in enumerate(self.units):
            if i != self.ui:
                off = -(un.x - x0) * sa + (un.y - y0) * ca
                if abs(off) < 100:
                    mark(un.x, un.y, un.z + 10, un.gun.char, pair(C["deep"], self.unit_fg(un)))
        ix, iy, exact = self.impact_estimate()
        mark(ix, iy, height(ix, iy) if not exact else self.pred[1].z, "X" if exact else "+",
             pair(colors.readable(C["shell"], sky), sky) | curses.A_BOLD)
        for p in self.projectiles:
            mark(p.x, p.y, p.z, "●", pair(C["deep"], C["shell_bg"]) | curses.A_BOLD)
        mark(u.x, u.y, u.z + 10, u.gun.char, pair(C["deep"], self.unit_fg(u)) | curses.A_BOLD)
        # what the main view shows: a bracket on the bottom edge
        cx, cy, vaz, s0, span = self.v
        va = math.radians(vaz)
        ax, ay = cx + s0 * math.cos(va), cy + s0 * math.sin(va)
        bx, by = ax + span * math.cos(va), ay + span * math.sin(va)
        c1, c2 = sorted((col_of(ax, ay), col_of(bx, by)))
        c1, c2 = max(0, c1), min(mw - 1, c2)
        if c1 <= c2:
            self.put(top + mh + 1, left + 1 + c1, "━" * (c2 - c1 + 1), colors.ink("accent", bold=True))
            self.put(top + mh + 1, left + 1 + c1, "┗", colors.ink("accent", bold=True))
            self.put(top + mh + 1, left + 1 + c2, "┛", colors.ink("accent", bold=True))

    def draw_fullmap(self):
        mw, mh = self.W - 2, self.H - 5
        cx, cy, width = self.mapview
        mpc = width / mw
        km = f"{width / 1000:.1f} km" if width >= 1000 else f"{width:.0f} m"
        self.draw_map(self.vt, 0, mw, mh, cx - width / 2, cy + mh * mpc, mpc,
                      f"MAP  {km} wide  ·  1 char = {mpc:.0f} m  ·  N up",
                      f"arrows pan  +/- zoom  Home fit  u centre on gun  {self.hint('aim_gui')} dial  "
                      f"Esc back  {self.hint('map')} off")

    def draw_gauge(self):
        """Pitch dial (side view) + yaw compass (top view, N up, like the map)."""
        u, g = self.unit, self.unit.gun
        top, left, w, h = self.vt, 0, 34, 9
        dim = curses.A_DIM
        self.frame(top, left, h, w)
        for r in range(1, h - 1):
            self.put(top + r, left + 16, "│", colors.ink("faint"))
        self.put(top, left + 2, f" pitch {u.elev:.2f}° ", colors.ink("accent", bold=True))
        self.put(top, left + 18, f" yaw {u.az:.2f}° ", colors.ink("accent", bold=True))

        # pitch: quarter dial, origin bottom-left; '.' marks the allowed arc
        ox, oy, R = left + 2, top + h - 2, 6
        for e in range(0, 91, 5):
            c = ox + int(round(R * math.cos(math.radians(e)) * 2))
            r = oy - int(round(R * math.sin(math.radians(e))))
            ok = g.elev_min <= e <= g.elev_max
            self.put(r, c, "." if ok else " ", colors.classic(1) if ok else dim)
        er = math.radians(u.elev)
        for k in (i / 2 for i in range(2, 2 * R)):
            self.put(oy - int(round(k * math.sin(er))), ox + int(round(k * math.cos(er) * 2)),
                     slope_char(u.elev), colors.classic(2) | curses.A_BOLD)
        self.put(oy, ox, "o", curses.A_BOLD)

        # yaw: compass, east = 0 deg, counter-clockwise (same as the minimap)
        cx, cy, R = left + 25, top + 4, 3
        for lab, dx, dy in (("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("W", -1, 0)):
            self.put(cy + dy * R, cx + dx * R * 2, lab, dim)
        ar = math.radians(u.az)
        for k in (i / 2 for i in range(2, 2 * R)):
            self.put(cy - int(round(k * math.sin(ar))), cx + int(round(k * math.cos(ar) * 2)),
                     slope_char(u.az), colors.classic(2) | curses.A_BOLD)
        self.put(cy - int(round(R * math.sin(ar))), cx + int(round(R * math.cos(ar) * 2)),
                 "*", colors.classic(2) | curses.A_BOLD)
        wx, wy = self.wind
        if math.hypot(wx, wy) > 0.5:     # wind: 'w' on the compass rim, pointing downwind
            aw = math.atan2(wy, wx)
            self.put(cy - int(round(R * math.sin(aw))), cx + int(round(R * math.cos(aw) * 2)),
                     "w", colors.classic(4) | curses.A_BOLD)
        self.put(cy, cx, "o", curses.A_BOLD)

    def draw_aim(self):
        """Precision dial: big needle for the selected axis, a vernier strip, typed entry."""
        u, g = self.unit, self.unit.gun
        pitch = self.aim == "pitch"
        step = AIM_STEPS[self.aim_step]
        val = u.elev if pitch else u.az
        w, h = min(self.W - 2, 66), min(self.H - 2, 22)
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        if self.map_mode == 2 and self.mapview:
            # full map: dial on the side away from the gun, so the aim line stays visible
            gun_right = u.x > self.mapview[0]
            left = 1 if gun_right else max(0, self.W - w - 1)
            top = max(self.vt, self.H - h - 2)
        self.box(top, left, h, w, f"AIMING DIAL · {self.aim.upper()}")
        txt, dim, acc = colors.ink("text"), colors.ink("dim"), colors.ink("accent", bold=True)
        sel = pair(C["text"], C["sel"]) | curses.A_BOLD
        self.put(top + 1, left + 3, f" pitch {u.elev:7.2f}° ", sel if pitch else txt)
        self.put(top + 1, left + 22, f" yaw {u.az:7.2f}° ", txt if pitch else sel)
        self.put(top + 1, left + 40, "Tab switch", dim)
        x = left + 3
        self.put(top + 2, x, "step", dim)
        x += 5
        for i, st in enumerate(AIM_STEPS):
            lab = f" {st:g}° "
            self.put(top + 2, x, lab, sel if i == self.aim_step else dim)
            x += len(lab) + 1
        # dial
        rows = h - 11                          # free rows between the header and the vernier
        needle = colors.ink("shell", bold=True)
        if pitch:                              # quarter dial sitting on its baseline
            R = max(3, min(rows - 1, (w - 8) // 4))
            cx, cy = left + w // 2 - 2 * R, top + 4 + R
            lo, hi = g.elev_min, g.elev_max
            for i in range(-4, 37):
                e = i * 2.5
                c = cx + int(round(R * 2 * math.cos(math.radians(e))))
                r = cy - int(round(R * math.sin(math.radians(e))))
                ok = lo <= e <= hi
                self.put(r, c, ("+" if e % 15 == 0 else "·") if ok else "·",
                         colors.ink("good") if ok else colors.ink("faint"))
            self.put(cy - R - 1, cx - 1, "90", dim)
            self.put(cy, cx + 2 * R + 2, "0", dim)
        else:
            R = max(2, (rows - 3) // 2)
            cx, cy = left + w // 2, top + 5 + R
            for e in range(0, 360, 15):
                c = cx + int(round(R * 2 * math.cos(math.radians(e))))
                r = cy - int(round(R * math.sin(math.radians(e))))
                self.put(r, c, "+" if e % 45 == 0 else "·", colors.ink("good"))
            for lab, dx, dy in (("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("W", -1, 0)):
                self.put(cy + dy * (R + 1), cx + dx * (R * 2 + 2), lab, acc)
        ang = math.radians(val)
        for k in range(1, 2 * R):
            rr = k / 2
            self.put(cy - int(round(rr * math.sin(ang))), cx + int(round(rr * 2 * math.cos(ang))),
                     "●" if k == 2 * R - 1 else "•", needle)
        self.put(cy, cx, "◉", txt | curses.A_BOLD)
        # vernier: one character per step, labels every 10 steps. For yaw it runs
        # right to left, so the strip moves the same way as the needle.
        vw = w - 6
        vy = top + h - 6
        mid = vw // 2
        base = round(val / step)
        sign = 1 if pitch else -1
        strip, labels = [], [" "] * vw
        for i in range(vw):
            n = base + sign * (i - mid)
            strip.append("┃" if n % 10 == 0 else ("╵" if n % 5 == 0 else "·"))
            if n % 10 == 0:
                lab = f"{round(n * step if pitch else (n * step) % 360, 2):g}"
                p = i - len(lab) // 2
                if 0 <= p and p + len(lab) <= vw and all(ch == " " for ch in labels[max(0, p - 1):p + len(lab) + 1]):
                    labels[p:p + len(lab)] = lab
        self.put(vy, left + 3, "".join(strip), colors.ink("good"))
        self.put(vy + 1, left + 3, "".join(labels), dim)
        self.put(vy - 1, left + 3 + mid, "▼", acc)
        if pitch:
            tbl = firing_table(u.charge.velocity, u.shell.drag)
            self.put(vy - 1, left + 3, f"flat range {table_lookup(tbl, u.elev, 0):.0f} m", dim)
        # typed entry
        if self.entry is not None:
            self.put(top + h - 4, left + 3, f" set {self.aim} to: {self.entry}█ ", sel)
            self.put(top + h - 4, left + 3 + len(self.entry) + 20, "Enter apply  Esc cancel", dim)
        else:
            self.put(top + h - 4, left + 3, "type a number to set it exactly (e.g. 42.5 Enter)", dim)
        self.hints(top + h - 3, left + 3, [("←→", "turn, hold = faster"), ("PgUp/PgDn", "x10"),
                                           ("↑↓ +/-", "step"), ("Tab", "yaw/pitch")],
                   limit=left + w - 2)
        self.hints(top + h - 2, left + 3, [(self.hint("fire"), "fire"),
                                           ("Enter/Esc", "close")], limit=left + w - 2)

    def draw_graph(self):
        if self.graph == 3:
            return self.draw_table()
        u = self.unit
        idx = self.graph - 1
        unit_s = "m" if idx == 0 else "s"
        gh, gw = min(16, self.vh - 1), min(62, self.W - 2)
        top, left = self.vt + self.vh - gh, self.W - gw
        if self.graph_left() or (self.right_rows and gh > self.vh - self.right_rows):
            left = 0
        tables = [firing_table(c.velocity, u.shell.drag) for c in u.gun.charges]
        vmax = max(r[idx] for t in tables for r in t) or 1
        title = ("range" if idx == 0 else "time of flight") + f" vs elevation · {u.shell.name}"
        self.frame(top, left, gh, gw, title)
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
        ids = [2, 4, 5, 3, 1]
        for k, tbl in enumerate(tables):
            cur = k == u.ci
            attr = colors.classic(ids[k % len(ids)]) | (curses.A_BOLD if cur else curses.A_DIM)
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

    def graph_left(self):
        """Own gun sits at the right edge (flipped view, or facing west in 2D): panels go left."""
        if self.flat:
            return not self.freecam and math.cos(math.radians(self.unit.az)) < 0
        return self.unit.flip and not self.freecam

    def draw_table(self):
        """Indirect firing table: per range, high-angle elevation and time of flight per charge."""
        u, g = self.unit, self.unit.gun
        tables = [firing_table(c.velocity, u.shell.drag) for c in g.charges]
        rmax = max(max(r[0] for r in t) for t in tables)
        gh = min(self.vh - 1, 26, self.vh - self.right_rows if self.right_rows else 99)
        n = max(3, gh - 6)
        step = next((s for s in (25, 50, 100, 200, 250, 500, 1000) if rmax / s <= n), 1000)
        ranges = [step * i for i in range(1, int(rmax // step) + 1)][:n]
        gh = min(len(ranges) + 6, self.vh - 1)
        ranges = ranges[:gh - 6]
        cw = 12
        gw = min(self.W, 10 + cw * len(tables) + 2)
        top = self.vt + self.vh - gh
        left = 0 if self.graph_left() else self.W - gw
        kind = "direct" if g.direct else "indirect"
        self.frame(top, left, gh, gw, f"{kind} firing table · {u.shell.name}")
        self.put(top + 1, left + 2, f"{'low' if g.direct else 'high'} angle, flat ground, no wind:"
                 " elev deg / tof s", curses.A_DIM)
        hdr = "range m " + "".join(f"{'ch ' + c.name:>{cw}}" for c in g.charges)
        self.put(top + 2, left + 2, hdr, curses.A_BOLD)
        for k in range(len(tables)):
            if k == u.ci:
                self.put(top + 2, left + 10 + k * cw, f"{'ch ' + g.charges[k].name:>{cw}}",
                         curses.A_BOLD | curses.A_REVERSE)
        cur = table_lookup(tables[u.ci], u.elev, 0)
        near = min(range(len(ranges)), key=lambda i: abs(ranges[i] - cur)) if ranges else -1
        for i, rng in enumerate(ranges):
            row = top + 3 + i
            self.put(row, left + 2, f"{rng:>6}", curses.A_BOLD if i == near else 0)
            for k, tbl in enumerate(tables):
                sol = (low_angle if g.direct else high_angle)(tbl, rng)
                ok = sol and g.elev_min <= sol[0] <= g.elev_max
                txt = f"{sol[0]:5.1f}/{sol[1]:4.1f}" if ok else "--"
                attr = colors.classic(2) | curses.A_BOLD if k == u.ci else curses.A_DIM
                self.put(row, left + 10 + k * cw, f"{txt:>{cw}}", attr)
        self.put(top + gh - 2, left + 2,
                 f"now: ch {u.charge.name} @ {u.elev:.2f}deg = {cur:.0f} m   [{self.keys.label('graph')}]",
                 curses.A_DIM)

    def hint(self, action):
        """First key bound to an action, for compact hints."""
        k = (self.keys.keys(action) or ["-"])[0]
        return {"space": "Space", "esc": "Esc", "tab": "Tab", "up": "↑", "down": "↓",
                "left": "←", "right": "→", "pgup": "PgUp", "pgdn": "PgDn"}.get(k, k)

    def hints(self, y, x, pairs, bg="sky", limit=None):
        """Key hints: key in accent colour, description dim. Returns the end column."""
        limit = limit or self.W
        for key, desc in pairs:
            n = len(key) + len(desc) + 3
            if x + n > limit:
                break
            self.put(y, x, key, colors.ink("accent", bg, True))
            self.put(y, x + len(key) + 1, desc, colors.ink("dim", bg))
            x += n
        return x

    def draw_hud(self):
        u, g = self.unit, self.unit.gun
        W = self.W
        bar = colors.ink("text", "bar")
        self.put(0, 0, " " * W, bar)
        x = 1

        def seg(text, fg="text", bold=False):
            nonlocal x
            self.put(0, x, text, colors.ink(fg, "bar", bold))
            x += len(text)

        def sep():
            seg("  │  ", "faint")

        if self.duel:
            seg("DUEL ", "accent", True)
            self.put(0, x, f" {u.name.upper()} ", pair(C["text"], self.unit_fg(u)) | curses.A_BOLD)
            x += len(u.name) + 2
            seg(" to play")
            sep()
            for i, un in enumerate(self.units):
                hp = max(0, un.hp)
                full = round(hp / 10)
                self.put(0, x, f"P{i + 1} ", pair(self.unit_fg(un), C["bar"]) | curses.A_BOLD)
                x += 3
                seg("█" * full, "good" if hp > 50 else "accent" if hp > 25 else "bad")
                seg("░" * (10 - full), "faint")
                seg(f" {hp}  ", "text")
        else:
            seg("SANDBOX", "accent", True)
            sep()
            alive = sum(t.alive for t in self.targets)
            seg("targets ")
            seg(f"{alive}/{len(self.targets)}", "target", True)
            seg(f"   shots {self.shots}")
        sep()
        if self.flat:
            seg("2D ", "accent", True)
        seg(g.name, "title", True)
        if g.prediction:
            seg(" FCS", "good")
        if g.sight:
            seg(" sight", "good")
        if self.duel and g.mobile:
            seg(f" fuel {u.fuel:.0f}m", "dim")
        if self.freecam:
            sep()
            seg("FREE CAMERA", "bad", True)
        wind = self.wind_text()
        if self.wind_on:
            a = math.degrees(math.atan2(self.wind[1], self.wind[0])) % 360
            arrow = "→↗↑↖←↙↓↘"[int((a + 22.5) // 45) % 8]
            if self.flat:
                arrow = "→" if self.wind[0] >= 0 else "←"
            wind = f"wind {arrow} {math.hypot(*self.wind):.1f} m/s"
        self.put(0, W - len(wind) - 2, wind, colors.ink("title", "bar"))

        # line 2: loadout and aim
        fuse = f"timed {u.fuse_time:.1f}s" if u.shell.fuse == "timed" else u.shell.fuse
        x = 1
        for m in ("move", "aim", "camera"):      # what the letter keys do (Tab)
            on = m == self.input_mode
            self.put(1, x, f" {m.upper()} ",
                     pair(C["deep"], C["accent"]) | curses.A_BOLD if on else colors.ink("dim"))
            x += len(m) + 2
        self.put(1, x + 1, self.hint("mode"), colors.ink("accent", bold=True))
        x += len(self.hint("mode")) + 4

        def item(label, value, fg="text"):
            nonlocal x
            self.put(1, x, label, colors.ink("dim"))
            x += len(label) + 1
            self.put(1, x, value, colors.ink(fg, bold=True))
            x += len(value) + 3

        item("shell", f"{u.shell.name} ({fuse})", "shell")
        item("charge", f"{u.charge.name} {u.charge.velocity:.0f}m/s")
        item("pitch", f"{u.elev:.2f}°", "accent")
        item("yaw", f"{u.az:.2f}°", "accent")
        item("step", f"{AIM_STEPS[self.aim_step]:g}°")
        if u.cooldown <= 0:
            self.put(1, x, " READY ", pair(C["deep"], C["good"]) | curses.A_BOLD)
        else:
            frac = 1 - u.cooldown / max(0.01, g.reload)
            n = int(frac * 8)
            self.put(1, x, "reload ", colors.ink("dim"))
            self.put(1, x + 7, "█" * n + "░" * (8 - n), colors.ink("accent"))

        # bottom line: message, prediction, or key hints
        y = self.H - 1
        if self.msg_t > 0:
            self.put(y, 1, self.msg, colors.ink("accent", bold=True))
            return
        if self.map_mode == 2:
            ix, iy, exact = self.impact_estimate()
            line = (f"Map: aim line ends at the {'computed impact (X)' if exact else 'flat-ground range (+)'}"
                    f" {math.hypot(ix - u.x, iy - u.y):.0f} m away")
            self.put(y, 1, line, colors.ink("dim"))
            return
        if self.pred:
            _, p = self.pred
            if p.result == "lost":
                line = "shell would be lost"
            else:
                d = math.hypot(p.x - u.x, p.y - u.y)
                wind = " · no wind correction" if self.wind_on else ""
                line = (f"FCS: {p.result} at {d:.0f} m, alt {p.z:.0f} m, tof {p.t:.1f} s{wind}"
                        if g.prediction else f"sight: lands ~{d:.0f} m ahead{wind}")
            self.put(y, 1, line, colors.ink("title"))
            hits = sum(self.target_state(t) == "hit" for t in self.targets)
            if hits:
                self.put(y, len(line) + 3, f" on target: {hits} hit{'s' if hits > 1 else ''} ",
                         pair(231, C["bad"]) | curses.A_BOLD)
            return
        k = self.hint
        zs, qd = f"{k('forward')}{k('back')}", f"{k('left')}{k('right')}"
        letters = {"move": [(zs, "drive"), (qd, "turn")],
                   "aim": [(zs, "pitch"), (qd, "yaw"), (",;", "step")],
                   "camera": [(zs, "cam up/down"), (qd, "cam left/right")]}[self.input_mode]
        self.hints(y, 1, [(k("mode"), "mode")] + letters + [
                          ("←→↑↓", "aim"), (k("fire"), "fire"),
                          (k("aim_gui"), "dial"), (k("map"), "map"), (k("graph"), "table"),
                          (k("gun_menu"), "gun"), (k("menu"), "menu"), (k("help"), "help")])
