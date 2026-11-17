"""Side view: the vertical slice of the world along the gun heading."""
import curses
import math

from .config import RELIEFS, SEA, VIEW_SPANS
from .world import BASE_CELL, chunks_ready, deform, raw_height, terrain_version, view_height


class ViewMixin:
    # ---------------------------------------------------------- view
    def view(self):
        """(cam_x, cam_y, heading_deg, s_start, span) of the vertical slice."""
        span = VIEW_SPANS[self.span_i]
        margin = span * 0.11
        if self.freecam:
            cx, cy, az = self.cam
        else:
            u = self.unit
            if u.flip:      # look backwards with the unit near the right edge
                return u.x, u.y, (u.az + 180) % 360, -(span - margin), span
            cx, cy, az = u.x, u.y, u.az
        return cx, cy, az, -margin, span

    def project(self, x, y):
        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        dx, dy = x - cx, y - cy
        s = dx * math.cos(a) + dy * math.sin(a)
        off = -dx * math.sin(a) + dy * math.cos(a)
        col = int(round((s - s0) / span * (self.vw - 1)))
        return col, off, s

    def frame_view(self):
        """Vertical scale follows the horizontal one (times the relief exaggeration),
        so a wider view is also flatter. Samples the surface once per column."""
        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        self.mpr = 2 * span / (self.vw - 1) / RELIEFS[self.relief_i]   # metres per row
        self.cols = []
        # zoomed out, sample the noise directly instead of generating every chunk
        coarse = span / (self.vw - 1) > 2 * BASE_CELL
        for col in range(self.vw):
            s = s0 + col / (self.vw - 1) * span
            x, y = cx + s * math.cos(a), cy + s * math.sin(a)
            dmg = deform(x, y)
            self.cols.append(((raw_height(x, y, 0.5 * span / self.vw) if coarse else view_height(x, y)) + dmg, dmg))
        lo = min(max(g, SEA) for g, _ in self.cols)
        hi = max(max(g, SEA) for g, _ in self.cols)
        window = (self.vh - 1) * self.mpr
        zbot = lo - 2 * self.mpr
        if hi > zbot + window * 0.8:       # tall terrain: keep the gun in the lower part
            zbot = max(zbot, min(hi - window * 0.8, self.unit.z - window * 0.4))
        snap = 4 * self.mpr                # move in steps so the view does not jitter
        self.zbot = math.floor(zbot / snap) * snap

    def zrow(self, z):
        return self.vt + (self.vh - 1) - int(round((z - self.zbot) / self.mpr))

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
        g = self.unit.gun
        u = self.unit
        if g.prediction or g.sight:
            key = (id(u), g.name, u.x, u.y, u.elev, u.az, u.ci, u.si, u.fuse_time, terrain_version[0],
                   chunks_ready())
            if key != getattr(self, "pred_key", None):
                self.pred, self.pred_key = u.predict(), key
        else:
            self.pred, self.pred_key = None, None
        self.frame_view()
        if self.map_mode == 2:
            self.draw_fullmap()
        else:
            self.draw_terrain()
            self.draw_ruler()
            self.draw_targets()
            if g.prediction:
                self.draw_prediction()
            elif g.sight:
                self.draw_sight()
            self.draw_projectiles()
            self.draw_units()
            self.draw_explosions()
            if self.map_mode == 1:
                self.draw_minimap()
            if self.gauge:
                self.draw_gauge()
            if self.graph:
                self.draw_graph()
        self.draw_hud()
        if self.handover:
            self.draw_handover()
        elif self.winner:
            self.draw_winner()
        if self.aim is not None:
            self.draw_aim()
        if self.menu is not None:
            self.draw_menu()
        if self.title is not None:
            self.draw_title()
        if self.help:
            self.draw_help()
        scr.refresh()

    def draw_terrain(self):
        rows = [[" "] * self.vw for _ in range(self.vh)]
        scorched, water = [], []
        sea_row = self.zrow(SEA) - self.vt
        for col, (h, dmg) in enumerate(self.cols):
            fz = (self.vh - 1) - (h - self.zbot) / self.mpr   # fractional row of the surface
            r = max(0, int(round(fz)))
            if r < self.vh:
                surf = "_" if fz - round(fz) > 0.15 else "#"   # surface in lower part of cell
                rows[r][col] = surf
                for rr in range(r + 1, self.vh):
                    rows[rr][col] = ":"
                if dmg < -1.5:
                    scorched.append((r, col, surf))
            if h < SEA and 0 <= sea_row < self.vh:
                water.append((col, r))
        green = curses.color_pair(1)
        for i, row in enumerate(rows):
            self.put(self.vt + i, 0, "".join(row), green)
        blue = curses.color_pair(4)
        for col, r in water:             # lake: surface line, empty water down to the bed
            self.put(self.vt + sea_row, col, "~", blue | curses.A_BOLD)
            for rr in range(sea_row + 1, min(r, self.vh)):
                self.put(self.vt + rr, col, " ")
        brown = curses.color_pair(3) | curses.A_DIM
        for r, col, surf in scorched:     # crater floors drawn in dim red
            self.put(self.vt + r, col, "w" if surf == "#" else "_", brown)

    def draw_ruler(self):
        """Distance ticks from the controlled unit along the view line."""
        _, _, _, s0, span = self.v
        _, _, su = self.project(self.unit.x, self.unit.y)
        row = self.vt + self.vh - 1
        tick = next(t for t in (250, 500, 1000, 2000, 5000) if span / t <= 10)
        n = int(span // tick) + 1
        for d in range(-n * tick, n * tick + 1, tick):
            col = int(round((su + d - s0) / span * (self.vw - 1)))
            if 0 <= col < self.vw:
                self.put(row, col, "|" if d else "^", curses.A_BOLD)
                if d and d % (2 * tick) == 0:
                    lab = f"{abs(d) // 1000}k" if abs(d) >= 1000 and abs(d) % 1000 == 0 else str(abs(d))
                    self.put(row, col + 1, lab, curses.A_DIM)

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
            attr = curses.A_BOLD | curses.color_pair(u.color) | (curses.A_REVERSE if i == self.ui else 0)
            self.put(r, col, u.gun.char, attr)
            if self.duel:
                tag = f"P{i + 1} {u.hp}" if u.hp > 0 else f"P{i + 1} KO"
                self.put(r - 2, col - len(tag) // 2, tag, curses.color_pair(u.color) | curses.A_BOLD)
            right = math.cos(math.radians(u.az - vaz)) >= 0
            if u.elev < 25:
                b = "-"
            elif u.elev < 65:
                b = "/" if right else "\\"
            else:
                b = "|"
            self.put(r - 1, col + (1 if right else -1) if b != "|" else col, b, curses.A_BOLD)

    def draw_prediction(self):
        path, p = self.pred
        cyan = curses.color_pair(4)
        for pt in path[::3]:
            col, off, _ = self.project(pt[0], pt[1])
            self.put(self.zrow(pt[2]), col, ".", cyan)
        if p.result != "lost":
            col, _, _ = self.project(p.x, p.y)
            self.put(self.zrow(p.z), col, "X", cyan | curses.A_BOLD)

    def draw_sight(self):
        """Tank gunsight: only the last part of the arc and a bracket on the impact."""
        path, p = self.pred
        cyan = curses.color_pair(4)
        for pt in path[int(len(path) * 0.75)::2]:
            col, _, _ = self.project(pt[0], pt[1])
            self.put(self.zrow(pt[2]), col, ".", cyan | curses.A_DIM)
        if p.result != "lost":
            col, _, _ = self.project(p.x, p.y)
            self.put(self.zrow(p.z), col - 1, "(+)", cyan | curses.A_BOLD)

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
            rr = max(1.0, e.radius / self.mpr)
            for dr in range(-math.ceil(rr), math.ceil(rr) + 1):
                for dc in range(-math.ceil(rc), math.ceil(rc) + 1):
                    if (dc / rc) ** 2 + (dr / rr) ** 2 <= 1:
                        self.put(row + dr, col + dc, "*", red)
