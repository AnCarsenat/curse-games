"""Side view: the vertical slice of the world along the gun heading."""
import curses
import math
import time

from . import colors
from .colors import C, pair
from .config import RELIEFS, SEA, VIEW_SPANS
from .world import (BASE_CELL, WORLD_TYPES, chunks_ready, deform, raw_height, shade_level,
                    terrain_version, view_height)

# terrain materials: surface colour, then the fill from just below it to deep down
MATERIALS = {
    "grass": ("grass_hi", ("soil1", "soil2", "soil3", "soil4")),
    "rock": ("rock_hi", ("rock1", "rock2", "rock3", "rock4")),
    "snow": ("snow", ("rock1", "rock2", "rock3", "rock4")),
    "sand": ("sand", ("sand1", "sand2", "sand3", "sand4")),
    "red": ("red_rock", ("red1", "red2", "red3", "red4")),
}
WATER = ("water", "water", "water2", "water3")


def ramp(fill, depth):
    """Fill colour `depth` rows below the surface: lighter near the top."""
    return fill[0 if depth < 2 else 1 if depth < 5 else 2 if depth < 9 else 3]
LOWER, UPPER = "▄", "▀"


def material(world_id, h):
    """Material of dry land at altitude h for the current world type."""
    if world_id == "dunes":
        return "sand" if shade_level(h) < 5 else "rock"
    if world_id == "canyons":
        return "grass" if h < 20 else "red"
    if world_id in ("flat", "classic"):
        return "grass"
    band = shade_level(h)
    if h < 6:
        return "sand"       # beaches
    return "grass" if band <= 3 else "rock" if band <= 5 else "snow"


class ViewMixin:
    # ---------------------------------------------------------- view
    def view(self):
        """(cam_x, cam_y, heading_deg, s_start, span) of the vertical slice."""
        span = VIEW_SPANS[self.span_i]
        margin = span * 0.11
        if self.flat:           # 2D: always looking north-side-on, east to the right
            if self.freecam:
                return self.cam[0], self.cam[1], 0.0, -span / 2, span
            u = self.unit
            east = math.cos(math.radians(u.az)) >= 0
            return u.x, u.y, 0.0, (-margin if east else -(span - margin)), span
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
        dx, dy = x - cx, y - cy
        s = dx * self._cos + dy * self._sin
        off = -dx * self._sin + dy * self._cos
        col = int(round((s - s0) / span * (self.vw - 1)))
        return col, off, s

    def frame_view(self):
        """Vertical scale follows the horizontal one (times the relief exaggeration),
        so a wider view is also flatter. Samples the surface once per column.
        Cached: nothing is resampled while the view and terrain stay the same."""
        cx, cy, az, s0, span = self.v
        a = math.radians(az)
        self._cos, self._sin = math.cos(a), math.sin(a)
        coarse = span / (self.vw - 1) > 2 * BASE_CELL
        key = (self.v, self.vw, self.vh, self.relief_i, terrain_version[0],
               0 if coarse else chunks_ready(), round(self.unit.z, 1), self.world_now, self.display,
               self.cam_dz if self.freecam else 0)
        if key == getattr(self, "_frame_key", None):
            return
        self._frame_key = key
        self._terrain_runs = None
        self.mpr = 2 * span / (self.vw - 1) / RELIEFS[self.relief_i]   # metres per row
        self.cols = []
        # zoomed out, sample the noise directly instead of generating every chunk
        detail = 0.5 * span / self.vw
        for col in range(self.vw):
            s = s0 + col / (self.vw - 1) * span
            x, y = cx + s * self._cos, cy + s * self._sin
            dmg = deform(x, y)
            self.cols.append(((raw_height(x, y, detail) if coarse else view_height(x, y)) + dmg, dmg))
        lo = min(max(g, SEA) for g, _ in self.cols)
        hi = max(max(g, SEA) for g, _ in self.cols)
        window = (self.vh - 1) * self.mpr
        zbot = lo - 2 * self.mpr
        if hi > zbot + window * 0.8:       # tall terrain: keep the gun in the lower part
            zbot = max(zbot, min(hi - window * 0.8, self.unit.z - window * 0.4))
        if self.freecam:
            zbot += self.cam_dz
        snap = 4 * self.mpr                # move in steps so the view does not jitter
        self.zbot = math.floor(zbot / snap) * snap

    def zrow(self, z):
        return self.vt + (self.vh - 1) - int(round((z - self.zbot) / self.mpr))

    # ---------------------------------------------------------- draw helpers
    def put(self, y, x, s, attr=0):
        if 0 <= y < self.H and x < self.W:
            if x < 0:
                s, x = s[-x:], 0
            try:
                self.scr.addstr(y, x, s[: self.W - x - (1 if y == self.H - 1 else 0)], attr)
            except curses.error:
                pass

    def over(self, y, x, s, fg, extra=0):
        """Text over the side view that keeps the background colour of each cell
        (sky, ground, water) instead of punching black holes in it."""
        r = y - self.vt
        if not (0 <= r < len(self.bg)):
            return self.put(y, x, s, pair(fg) | extra)
        row = self.bg[r]
        i = 0
        while i < len(s):
            c = x + i
            if not (0 <= c < self.vw):
                i += 1
                continue
            bg = row[c]
            j = i + 1
            while j < len(s) and 0 <= x + j < self.vw and row[x + j] == bg:
                j += 1
            self.put(y, c, s[i:j], pair(colors.readable(fg, bg), bg) | extra)
            i = j

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
        u = self.unit
        g = u.gun
        if g.prediction or g.sight:
            self.update_prediction()
        else:
            self.pred, self.pred_key = None, None
        if self.map_mode == 2:
            self.frame_view()
            self.draw_fullmap()
        else:
            self.frame_view()
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
            self.right_rows = 0             # rows used by the map panels on the right
            if self.map_mode == 1:
                if not self.flat:
                    self.draw_minimap()
                    self.right_rows = 15
                if self.vh - self.right_rows >= 10:
                    self.draw_slicemap(self.vt + self.right_rows)
                    self.right_rows += 9
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

    def update_prediction(self):
        """Recompute the FCS / sight arc when the aim changes. Newly generated terrain
        chunks only change it by centimetres, so they trigger at most 2 updates a second."""
        u, g = self.unit, self.unit.gun
        key = (id(u), g.name, u.x, u.y, u.elev, u.az, u.ci, u.si, u.fuse_time, terrain_version[0])
        now = time.perf_counter()
        old = getattr(self, "pred_key", None)
        if key != old:
            self.pred, self.pred_key = u.predict(), key
            self._pred_chunks, self._pred_t = chunks_ready(), now
        elif chunks_ready() != getattr(self, "_pred_chunks", None) and now - self._pred_t > 0.5:
            self.pred = u.predict()
            self._pred_chunks, self._pred_t = chunks_ready(), now

    # ---------------------------------------------------------- terrain
    def draw_terrain(self):
        if self._terrain_runs is None:
            self._terrain_runs = self._build_terrain()
        for y, x, text, attr in self._terrain_runs:
            self.put(y, x, text, attr)

    def _build_terrain(self):
        """Cells of the side view as (char, fg, bg) -> runs of addstr calls.
        Ground and water surfaces use half blocks, so the profile has twice the
        vertical resolution of the terminal."""
        vh, vw = self.vh, self.vw
        sky = C["sky"]
        world_id = WORLD_TYPES[self.world_now][0]
        chars = [[" "] * vw for _ in range(vh)]
        fgs = [[sky] * vw for _ in range(vh)]
        bgs = [[sky] * vw for _ in range(vh)]
        sea_h = (vh - 1) - (SEA - self.zbot) / self.mpr          # fractional row of the sea
        sea_half = int(math.floor(sea_h * 2 + 0.5))              # in half rows
        if self.display != "blocks":
            self._chars_terrain(world_id, chars, fgs, sea_h)
            return self._runs(chars, fgs, bgs)
        for col, (h, dmg) in enumerate(self.cols):
            fz = (vh - 1) - (h - self.zbot) / self.mpr
            half = int(math.floor(fz * 2 + 0.5))                 # surface in half rows
            under = h < SEA
            name, fill = MATERIALS["sand" if under else material(world_id, h)]
            top = C[name]
            fill = [C[f] for f in fill]
            sub = fill[0]
            if dmg < -1.5:
                top = C["scorch"]
            above = sky
            if under:                                            # water from the sea surface down
                r0 = sea_half // 2
                for r in range(max(0, r0), min(vh, half // 2 + 1)):
                    bgs[r][col] = C[ramp(WATER, r - r0)]
                above = bgs[min(vh - 1, max(0, half // 2))][col]
                if 0 <= r0 < vh:
                    if sea_half % 2:
                        chars[r0][col], fgs[r0][col], bgs[r0][col] = LOWER, C["water_hi"], sky
                    else:
                        chars[r0][col], fgs[r0][col] = UPPER, C["water_hi"]
            r = half // 2
            if r >= vh:
                continue
            if r >= 0:
                if half % 2:                 # surface in the lower half of the cell
                    chars[r][col], fgs[r][col], bgs[r][col] = LOWER, top, above
                else:                        # upper half: thin top layer over the fill
                    chars[r][col], fgs[r][col], bgs[r][col] = UPPER, top, sub
            for rr in range(max(0, r + 1), vh):
                bgs[rr][col] = ramp(fill, rr - r - 1)
                chars[rr][col] = " "
        return self._runs(chars, fgs, bgs)

    def _chars_terrain(self, world_id, chars, fgs, sea_h):
        """Character display: '#' or '_' on the surface, ':' below, '~' water."""
        vh = self.vh
        sea_row = int(round(sea_h))
        for col, (h, dmg) in enumerate(self.cols):
            fz = (vh - 1) - (h - self.zbot) / self.mpr
            r = max(0, int(round(fz)))
            under = h < SEA
            name, fill = MATERIALS["sand" if under else material(world_id, h)]
            top, sub = C[name], C[fill[0]]
            if r < vh:
                low = fz - round(fz) > 0.15             # surface in the lower part of the cell
                if dmg < -1.5:
                    chars[r][col], fgs[r][col] = ("_" if low else "w"), C["scorch"]
                else:
                    chars[r][col], fgs[r][col] = ("_" if low else "#"), top
                for rr in range(r + 1, vh):
                    chars[rr][col], fgs[rr][col] = ":", sub
            if under and 0 <= sea_row < vh:
                chars[sea_row][col], fgs[sea_row][col] = "~", C["water_hi"]

    def _runs(self, chars, fgs, bgs):
        vh, vw = self.vh, self.vw
        self.bg = bgs
        runs = []
        for r in range(vh):
            cr, fr, br = chars[r], fgs[r], bgs[r]
            c = 0
            while c < vw:
                f, b = fr[c], br[c]
                e = c + 1
                if cr[c] == " ":                 # blanks only care about the background
                    while e < vw and cr[e] == " " and br[e] == b:
                        e += 1
                    runs.append((self.vt + r, c, " " * (e - c), pair(C["text"], b)))
                else:
                    while e < vw and cr[e] == cr[c] and fr[e] == f and br[e] == b:
                        e += 1
                    runs.append((self.vt + r, c, cr[c] * (e - c), pair(f, b)))
                c = e
        return runs

    def draw_ruler(self):
        """Distance ticks from the controlled unit along the view line, on a strip."""
        _, _, _, s0, span = self.v
        _, _, su = self.project(self.unit.x, self.unit.y)
        row = self.vt + self.vh - 1
        strip = colors.ink("dim", "bar")
        self.put(row, 0, " " * self.vw, strip)
        self.bg[self.vh - 1] = [C["bar"]] * self.vw
        tick = next(t for t in (250, 500, 1000, 2000, 5000) if span / t <= 10)
        n = int(span // tick) + 1
        for d in range(-n * tick, n * tick + 1, tick):
            col = int(round((su + d - s0) / span * (self.vw - 1)))
            if 0 <= col < self.vw:
                self.put(row, col, "┃" if not d else "╵", colors.ink("accent" if not d else "text", "bar", True))
                if d and d % (2 * tick) == 0:
                    lab = f"{abs(d) // 1000}km" if abs(d) >= 1000 and abs(d) % 1000 == 0 else f"{abs(d)}m"
                    self.put(row, col + 1, lab, strip)

    def target_state(self, t):
        """How a target stands against the current aim:
        "hit"  - the computed shot (FCS / sight guns, no wind) will destroy it
        "line" - it is within blast radius of the firing line: right range = hit
        "off"  - the shell can't reach it on this heading; "dead" - destroyed."""
        if not t.alive:
            return "dead"
        u = self.unit
        blast = u.shell.blast
        if self.pred and self.pred[1].result != "lost":
            if math.dist(self.pred[1].pos, (t.x, t.y, t.z)) <= blast:
                return "hit"
        a = math.radians(u.az)
        dx, dy = t.x - u.x, t.y - u.y
        along = dx * math.cos(a) + dy * math.sin(a)
        off = -dx * math.sin(a) + dy * math.cos(a)
        return "line" if along > 0 and abs(off) <= blast else "off"

    def draw_targets(self):
        for t in self.targets:
            col, off, _ = self.project(t.x, t.y)
            if abs(off) > 80:
                continue
            state = self.target_state(t)
            row = self.zrow(t.z)
            if state == "hit":
                self.put(row, col, "T", pair(231, C["bad"]) | curses.A_BOLD)
                self.over(row - 1, col, "▼", C["bad"], curses.A_BOLD)
            elif state == "line":
                self.put(row, col, "T", pair(C["deep"], C["target"]) | curses.A_BOLD)
            else:
                self.over(row, col, "x" if state == "dead" else "t", C["dim"], curses.A_DIM)

    def unit_fg(self, u):
        return {4: C["title"], 5: C["target"]}.get(u.color, C["accent"])

    def draw_units(self):
        _, _, vaz, _, _ = self.v
        for i, u in enumerate(self.units):
            col, off, _ = self.project(u.x, u.y)
            if abs(off) > 100:
                continue
            r = self.zrow(u.z)
            fg = self.unit_fg(u)
            # solid badge so the gun stands out on any ground; the other player's is dimmer
            self.put(r, col, u.gun.char, pair(C["deep"], fg) | (curses.A_BOLD if i == self.ui else 0))
            if self.duel:
                tag = f"P{i + 1} {u.hp}" if u.hp > 0 else f"P{i + 1} KO"
                self.over(r - 2, col - len(tag) // 2, tag, fg, curses.A_BOLD)
            right = math.cos(math.radians(u.az - vaz)) >= 0
            if u.elev < 25:
                b = "-"
            elif u.elev < 65:
                b = "/" if right else "\\"
            else:
                b = "|"
            self.over(r - 1, col + (1 if right else -1) if b != "|" else col, b, C["text"], curses.A_BOLD)

    def draw_prediction(self):
        path, p = self.pred
        for pt in path[::3]:
            col, off, _ = self.project(pt[0], pt[1])
            self.over(self.zrow(pt[2]), col, "·", C["title"])
        if p.result != "lost":
            col, _, _ = self.project(p.x, p.y)
            self.over(self.zrow(p.z), col, "X", C["title"], curses.A_BOLD)

    def draw_sight(self):
        """Tank gunsight: only the last part of the arc and a bracket on the impact."""
        path, p = self.pred
        for pt in path[int(len(path) * 0.75)::2]:
            col, _, _ = self.project(pt[0], pt[1])
            self.over(self.zrow(pt[2]), col, "·", C["title"], curses.A_DIM)
        if p.result != "lost":
            col, _, _ = self.project(p.x, p.y)
            self.over(self.zrow(p.z), col - 1, "(+)", C["title"], curses.A_BOLD)

    def draw_projectiles(self):
        """Shell: fading trail (bright near the shell), a bold badge for the shell
        itself, and an arrow on the screen edge while it is out of view."""
        fades = [C["trail1"], C["trail2"], C["trail3"], C["trail4"]]
        badge = pair(C["deep"], C["shell_bg"]) | curses.A_BOLD
        top, bottom = self.vt, self.vt + self.vh - 2
        for p in self.projectiles:
            pts = p.trail
            n = len(pts)
            step = max(1, n // 80)
            for i in range(n - 1 - step, -1, -step):
                age = (n - 1 - i) / 160            # 0 = just now, 1 = oldest kept
                col, _, _ = self.project(pts[i][0], pts[i][1])
                fg = fades[min(3, int(age * 4))]
                self.over(self.zrow(pts[i][2]), col, "•" if age < 0.25 else "·", fg,
                          curses.A_BOLD if age < 0.25 else 0)
            col, off, s = self.project(p.x, p.y)
            row = self.zrow(p.z)
            if top <= row <= bottom and 0 <= col < self.vw:
                self.put(row, col, p.shell.char, badge)
                continue
            # off screen: arrow on the nearest edge with height / distance
            _, _, su = self.project(self.unit.x, self.unit.y)
            if col < 0 or col >= self.vw:
                r = min(bottom, max(top, row))
                left = col < 0
                lab = f"◀ {abs(s - su):.0f}m" if left else f"{abs(s - su):.0f}m ▶"
                self.put(r, 0 if left else self.vw - len(lab), lab, badge)
            else:
                above = row < top
                lab = f"▲ {p.z:.0f}m" if above else "▼"
                self.put(top if above else bottom, max(0, min(self.vw - len(lab), col - 1)), lab, badge)

    def draw_explosions(self):
        _, _, _, _, span = self.v
        for e in self.explosions:
            col, off, _ = self.project(e.pos[0], e.pos[1])
            if abs(off) > e.radius:
                continue
            row = self.zrow(e.pos[2])
            rc = max(1.0, e.radius / span * (self.vw - 1))
            rr = max(1.0, e.radius / self.mpr)
            hot = e.ttl > 0.4
            for dr in range(-math.ceil(rr), math.ceil(rr) + 1):
                for dc in range(-math.ceil(rc), math.ceil(rc) + 1):
                    d = (dc / rc) ** 2 + (dr / rr) ** 2
                    if d <= 1:
                        fg = C["shell"] if d < 0.3 and hot else C["bad"]
                        self.over(row + dr, col + dc, "*" if d < 0.6 else "·", fg, curses.A_BOLD)
