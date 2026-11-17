"""Panels drawn over the view: maps, gauge, aiming dial, graphs/tables and the HUD."""
import curses
import math

from .config import AIM_STEPS, SEA
from .world import deform, raw_height, shade_level
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
            shades = " `,:;=%#"     # no . - | / \\ + X: those mark the aim line and barrels
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
                        ch = cells[(mk, i, jj)] = "~" if h < SEA else shades[1 + shade_level(h)]
                    line.append(ch)
                rows.append("".join(line))
            self.map_cache[key] = rows
        dim = curses.A_DIM
        self.put(top, left, "+" + "-" * mw + "+", dim)
        self.put(top, left + 2, f" {title} ", curses.A_BOLD)
        for j, row in enumerate(rows):
            self.put(top + 1 + j, left, "|", dim)
            self.put(top + 1 + j, left + 1, row, curses.color_pair(1) | dim)
            start = row.find("~")
            while start >= 0:            # water in blue
                end = start
                while end < len(row) and row[end] == "~":
                    end += 1
                self.put(top + 1 + j, left + 1 + start, row[start:end], curses.color_pair(4))
                start = row.find("~", end)
            self.put(top + 1 + j, left + 1 + mw, "|", dim)
        self.put(top + mh + 1, left, "+" + "-" * mw + "+", dim)
        if foot:
            self.put(top + mh + 1, left + 2, f" {foot} ", dim)

        def plot(x, y, ch, attr):
            c = left + 1 + math.floor(x / mpc) - i0
            r = top + 1 + j0 - math.floor(y / (2 * mpc))
            if left < c <= left + mw and top < r <= top + mh:
                self.put(r, c, ch, attr)
                return c, r
            return None

        # aim line: from the gun to where the shell should land
        u = self.unit
        ix, iy, exact = self.impact_estimate()
        n = max(2, min(600, int(math.hypot(ix - u.x, iy - u.y) / mpc * 1.5)))
        cyan = curses.color_pair(4)
        for k in range(1, n):
            plot(u.x + (ix - u.x) * k / n, u.y + (iy - u.y) * k / n, ".", cyan | curses.A_BOLD)
        for t in self.targets:
            plot(t.x, t.y, "T" if t.alive else "x", curses.color_pair(5) | curses.A_BOLD)
        plot(ix, iy, "X" if exact else "+", curses.color_pair(2) | curses.A_BOLD)
        yellow = curses.color_pair(2)
        for p in self.projectiles:
            for pt in p.trail[::4]:
                plot(pt[0], pt[1], "'", yellow | dim)
            plot(p.x, p.y, "o", yellow | curses.A_BOLD)
        for e in self.explosions:
            plot(e.pos[0], e.pos[1], "*", curses.color_pair(3) | curses.A_BOLD)
        # units, each with a short barrel pointing along its heading
        for i, un in enumerate(self.units):
            pos = plot(un.x, un.y, un.gun.char, curses.A_BOLD | curses.color_pair(un.color)
                       | (curses.A_REVERSE if i == self.ui else 0))
            if not pos:
                continue
            a = math.radians(un.az)
            for k in (1, 2):
                c = pos[0] + int(round(2 * k * math.cos(a)))
                r = pos[1] - int(round(k * math.sin(a)))
                if left < c <= left + mw and top < r <= top + mh:
                    self.put(r, c, slope_char(un.az), curses.A_BOLD | curses.color_pair(un.color or 2))

    def draw_minimap(self):
        mw, mh = 26, 13
        x0, y0, side = self.map_region()
        mpc = side / mw
        self.draw_map(self.vt, self.W - mw - 2, mw, mh, x0, y0 + side, mpc,
                      f"map {side / 1000:.1f} km", f"{self.keys.label('map')}: full")

    def draw_fullmap(self):
        mw, mh = self.W - 2, self.H - 5
        cx, cy, width = self.mapview
        mpc = width / mw
        km = f"{width / 1000:.1f} km" if width >= 1000 else f"{width:.0f} m"
        self.draw_map(self.vt, 0, mw, mh, cx - width / 2, cy + mh * mpc, mpc,
                      f"MAP  {km} wide  (1 char = {mpc:.0f} m)  N up",
                      "arrows/letters pan  +/- or PgUp/PgDn zoom  Home fit  u centre on gun  "
                      f"Esc back  {self.keys.label('map')} off")

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
        self.put(top, left + 2, f" pitch {u.elev:.2f} ", curses.A_BOLD)
        self.put(top, left + 18, f" yaw {u.az:.2f} ", curses.A_BOLD)

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
        wx, wy = self.wind
        if math.hypot(wx, wy) > 0.5:     # wind: 'w' on the compass rim, pointing downwind
            aw = math.atan2(wy, wx)
            self.put(cy - int(round(R * math.sin(aw))), cx + int(round(R * math.cos(aw) * 2)),
                     "w", curses.color_pair(4) | curses.A_BOLD)
        self.put(cy, cx, "o", curses.A_BOLD)

    def draw_aim(self):
        """Precision dial: big needle for the selected axis plus a vernier strip."""
        u, g = self.unit, self.unit.gun
        pitch = self.aim == "pitch"
        step = AIM_STEPS[self.aim_step]
        val = u.elev if pitch else u.az
        w, h = min(self.W - 2, 64), min(self.H - 2, 21)
        top, left = max(0, (self.H - h) // 2), max(0, (self.W - w) // 2)
        self.box(top, left, h, w, f"AIMING DIAL - {self.aim.upper()}")
        rev, bold = curses.A_REVERSE, curses.A_REVERSE | curses.A_BOLD
        self.put(top + 1, left + 2, f"pitch {u.elev:7.2f} deg", bold if pitch else rev)
        self.put(top + 1, left + 24, f"yaw {u.az:7.2f} deg", rev if pitch else bold)
        steps = "  ".join((f"[{s:g}]" if i == self.aim_step else f" {s:g} ") for i, s in enumerate(AIM_STEPS))
        self.put(top + 2, left + 2, f"precision: {steps} deg", rev)
        # dial
        rows = h - 10                          # free rows between the header and the vernier
        if pitch:                              # quarter dial sitting on its baseline
            R = max(3, min(rows - 1, (w - 8) // 4))
            cx, cy = left + w // 2 - 2 * R, top + 4 + R
            lo, hi = g.elev_min, g.elev_max
            for i in range(-4, 37):
                e = i * 2.5
                c = cx + int(round(R * 2 * math.cos(math.radians(e))))
                r = cy - int(round(R * math.sin(math.radians(e))))
                ok = lo <= e <= hi
                self.put(r, c, ("+" if e % 15 == 0 else ".") if ok else " ",
                         curses.A_REVERSE | (curses.A_BOLD if ok else curses.A_DIM))
            self.put(cy - R - 1, cx - 1, "90", rev | curses.A_DIM)
            self.put(cy, cx + 2 * R + 2, "0", rev | curses.A_DIM)
            ang = math.radians(val)
        else:
            R = max(2, (rows - 3) // 2)
            cx, cy = left + w // 2, top + 5 + R
            for e in range(0, 360, 15):
                c = cx + int(round(R * 2 * math.cos(math.radians(e))))
                r = cy - int(round(R * math.sin(math.radians(e))))
                self.put(r, c, "+" if e % 45 == 0 else ".", rev)
            for lab, dx, dy in (("N", 0, -1), ("S", 0, 1), ("E", 1, 0), ("W", -1, 0)):
                self.put(cy + dy * (R + 1), cx + dx * (R * 2 + 2), lab, bold)
            ang = math.radians(val)
        for k in range(1, 2 * R):
            rr = k / 2
            self.put(cy - int(round(rr * math.sin(ang))), cx + int(round(rr * 2 * math.cos(ang))),
                     "o" if k == 2 * R - 1 else "*", curses.color_pair(2) | curses.A_BOLD)
        self.put(cy, cx, "@", bold)
        # vernier: one character per step, labels every 10 steps
        vw = w - 6
        vy = top + h - 5
        mid = vw // 2
        base = round(val / step)
        strip, labels = [], [" "] * vw
        for i in range(vw):
            n = base + i - mid
            strip.append("|" if n % 10 == 0 else ("+" if n % 5 == 0 else "."))
            if n % 10 == 0:
                lab = f"{round(n * step if pitch else (n * step) % 360, 2):g}"
                p = i - len(lab) // 2
                if 0 <= p and p + len(lab) <= vw and all(ch == " " for ch in labels[max(0, p - 1):p + len(lab) + 1]):
                    labels[p:p + len(lab)] = lab
        self.put(vy, left + 3, "".join(strip), rev)
        self.put(vy + 1, left + 3, "".join(labels), rev | curses.A_DIM)
        self.put(vy - 1, left + 3 + mid, "v", bold)
        if pitch:
            tbl = firing_table(u.charge.velocity, u.shell.drag)
            self.put(vy - 1, left + 3, f"flat range {table_lookup(tbl, u.elev, 0):.0f} m", rev)
        self.put(top + h - 2, left + 2, "Left/Right turn  PgUp/PgDn x10  Up/Down or +/- step  Tab yaw/pitch",
                 rev | curses.A_DIM)
        self.put(top + h - 1, left + 2, f"{self.keys.label('fire')}: fire   Enter/Esc/"
                 f"{self.keys.label('aim_gui')}: close", rev | curses.A_DIM)

    def draw_graph(self):
        if self.graph == 3:
            return self.draw_table()
        u = self.unit
        idx = self.graph - 1
        unit_s = "m" if idx == 0 else "s"
        gh, gw = min(16, self.vh - 1), min(62, self.W - 2)
        top, left = self.vt + self.vh - gh, self.W - gw
        if self.graph_left() or (self.map_mode == 1 and gh > self.vh - 15):
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

    def graph_left(self):
        """Flipped view: own gun sits at the right edge, so panels go left."""
        return self.unit.flip and not self.freecam

    def draw_table(self):
        """Indirect firing table: per range, high-angle elevation and time of flight per charge."""
        u, g = self.unit, self.unit.gun
        tables = [firing_table(c.velocity, u.shell.drag) for c in g.charges]
        rmax = max(max(r[0] for r in t) for t in tables)
        gh = min(self.vh - 1, 26, self.vh - 15 if self.map_mode == 1 else 99)
        n = gh - 6
        step = next((s for s in (25, 50, 100, 200, 250, 500, 1000) if rmax / s <= n), 1000)
        ranges = [step * i for i in range(1, int(rmax // step) + 1)][:n]
        gh = len(ranges) + 6
        cw = 12
        gw = min(self.W, 10 + cw * len(tables) + 2)
        top = self.vt + self.vh - gh
        left = 0 if self.graph_left() else self.W - gw
        for r in range(gh):
            self.put(top + r, left, " " * gw)
        self.put(top, left, "+" + "-" * (gw - 2) + "+", curses.A_DIM)
        self.put(top + gh - 1, left, "+" + "-" * (gw - 2) + "+", curses.A_DIM)
        for r in range(1, gh - 1):
            self.put(top + r, left, "|", curses.A_DIM)
            self.put(top + r, left + gw - 1, "|", curses.A_DIM)
        kind = "direct" if g.direct else "indirect"
        self.put(top, left + 2, f" {kind} firing table - {u.shell.name} ", curses.A_BOLD)
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
                attr = curses.color_pair(2) | curses.A_BOLD if k == u.ci else curses.A_DIM
                self.put(row, left + 10 + k * cw, f"{txt:>{cw}}", attr)
        self.put(top + gh - 2, left + 2,
                 f"now: ch {u.charge.name} @ {u.elev:.2f}deg = {cur:.0f} m   [{self.keys.label('graph')}]",
                 curses.A_DIM)

    def hint(self, action):
        """First key bound to an action, for compact hints."""
        return (self.keys.keys(action) or ["-"])[0]

    def draw_hud(self):
        u, g = self.unit, self.unit.gun
        alive = sum(t.alive for t in self.targets)
        tags = (" [FCS]" if g.prediction else "") + (" [sight]" if g.sight else "")
        cam = " | FREE CAMERA" if self.freecam else ""
        bar = curses.A_REVERSE | curses.A_BOLD
        if self.duel:
            hp = "  ".join(f"P{i + 1} {x.hp}HP" for i, x in enumerate(self.units))
            fuel = f" | fuel {u.fuel:.0f}m" if g.mobile else ""
            self.put(0, 0, f" DUEL {u.name.upper()}'s turn | {g.name}{tags}{fuel} | {hp} | "
                     f"{self.wind_text()}{cam}".ljust(self.W), bar)
            self.put(0, 6, f"{u.name.upper()}'s turn", bar | curses.color_pair(u.color))
        else:
            self.put(0, 0, f" SANDBOX | {g.name}{tags} | targets {alive}/{len(self.targets)}"
                     f"  shots {self.shots} | {self.wind_text()}{cam}".ljust(self.W), bar)
        fuse = f"timed {u.fuse_time:.1f}s" if u.shell.fuse == "timed" else u.shell.fuse
        ready = "READY" if u.cooldown <= 0 else f"reload {u.cooldown:.1f}s"
        self.put(1, 0, f" {u.shell.name} ({fuse}) | charge {u.charge.name} {u.charge.velocity:.0f}m/s | "
                 f"pitch {u.elev:.2f}  yaw {u.az:.2f}  step {AIM_STEPS[self.aim_step]:g}deg | {ready}",
                 curses.color_pair(2) | curses.A_BOLD if u.cooldown <= 0 else curses.A_DIM)
        if self.msg_t > 0:
            line = self.msg
        elif self.map_mode == 2:
            ix, iy, exact = self.impact_estimate()
            line = (f"Map: aim line ends at the {'computed impact (X)' if exact else 'flat-ground range (+)'}"
                    f" {math.hypot(ix - u.x, iy - u.y):.0f} m away")
        elif self.pred:
            _, p = self.pred
            if p.result == "lost":
                line = "Shell would be lost"
            else:
                d = math.hypot(p.x - u.x, p.y - u.y)
                wind = "  (no wind correction)" if self.wind_on else ""
                if g.prediction:
                    line = f"FCS: {p.result} at {d:.0f} m, alt {p.z:.0f} m, tof {p.t:.1f} s{wind}"
                else:
                    line = f"Sight: lands ~{d:.0f} m ahead{wind}"
        else:
            k = self.hint
            line = (f"arrows aim  {k('step_up')}/{k('step_down')} step  {k('forward')}{k('back')} drive  "
                    f"{k('fire')} fire  {k('aim_gui')} dial  {k('map')} map  {k('graph')} table  "
                    f"{k('gun_menu')} gun  {k('menu')} menu  {k('help')} help")
        self.put(self.H - 1, 0, " " + line)
