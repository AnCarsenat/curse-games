"""Game state and rules (turns, wind, damage). Input and drawing live in the mixins."""
import math
import random

from .config import CHUNK, DT, TIME_SCALE, WIND_MAX, WORLD, Y0
from .world import (chunk_of, find_land, find_land_line, generate_pending, height, is_water,
                    make_crater, new_world)
from .content import GUNS
from .entities import Explosion, Target, Unit
from .keys import Keymap
from . import save
from .controls import ControlsMixin
from .view import ViewMixin
from .panels import PanelsMixin
from .overlays import OverlaysMixin


class Game(ControlsMixin, ViewMixin, PanelsMixin, OverlaysMixin):
    def __init__(self):
        self.cam = [0.0, Y0, 0.0]
        self.H, self.W = 24, 80   # real size known after the first draw
        self.graph = 0          # 0 off, 1 range, 2 time of flight, 3 firing table
        self.help = False
        self.menu = None        # selected row while a settings page is open
        self.menu_page = "game"  # "gun" or "game"
        self.wind_on = True
        self.span_i = 0         # index into VIEW_SPANS
        self.relief_i = 1       # index into RELIEFS (vertical exaggeration)
        self.world_type = 0     # index into WORLD_TYPES used for the next new world
        self.aim = None         # precision dial: None closed, else "pitch" or "yaw"
        self.entry = None       # number being typed in the dial
        self.input_mode = "move"  # what the letter keys do: move / aim / camera (Tab)
        self.display = "blocks"   # blocks / chars / mono (game settings > Display)
        self.flat_next = False  # setting: next game is 2D (everything on the slice)
        self.flat = False       # the current game is 2D
        self.cam_dz = 0.0       # camera mode: vertical offset of the side view (m)
        self.aim_step = 1       # index into AIM_STEPS: step of the arrows and the dial
        self.map_mode = 1       # 0 off, 1 corner minimap, 2 full-screen map
        self.mapview = None     # full map: [centre x, centre y, width in metres]
        self.map_cache = {}
        self.pred = None        # (path, projectile) predicted this frame (FCS / sight)
        self.keymenu = None     # selected action while the key-binding page is open
        self.capturing = False  # waiting for a key to bind
        self.title = 0          # selected mode while the mode-select screen is open
        self.gauge = True
        self.keys = Keymap()
        self.acc = 0.0
        self.new_game("sandbox")
        self.played = False     # nothing worth saving yet (set by firing / starting a game)
        self.saved = save.read()   # last game, offered on the title screen
        self.say(self.keys.error or f"Welcome! {self.keys.label('help')}: all keys", 4)

    @property
    def unit(self):
        return self.units[self.ui]

    @property
    def duel(self):
        return self.mode == "duel"

    def say(self, text, t=3.0):
        self.msg, self.msg_t = text, t

    def new_game(self, mode):
        self.mode = mode
        self.flat = self.flat_next
        self.played, self.saved = True, None
        self.seed = random.randrange(1 << 30)
        new_world(self.seed, self.world_type)
        self.world_now = self.world_type
        self.map_cache = {}
        if self.map_mode == 2:
            self.map_mode = 1
        self.explored = set()   # chunks seen (units, impacts); the minimap covers them
        self.aim = self.entry = None
        self.projectiles, self.explosions = [], []
        self.freecam = False
        self.input_mode = "move"
        self.new_wind()
        self.winner = None      # duel: end-of-game text
        self.handover = False   # duel: waiting for the next player to take the keyboard
        self.turn_fired = False
        self.report = ""        # duel: result of the last shot, shown at handover
        self.shots = 0
        self.ui = 0
        if mode == "duel" and self.flat:
            x = random.uniform(450, 650)
            p1 = Unit(GUNS[0], *find_land_line(x, Y0), "Player 1", 4)
            p2 = Unit(GUNS[0], *find_land_line(WORLD - x, Y0), "Player 2", 5)
            p1.az, p2.az = 0.0, 180.0
            p2.flip = True
            self.units, self.targets = [p1, p2], []
            self.start_turn(0)
            self.say("Duel (2D)", 2)
        elif mode == "duel":
            x, dy = random.uniform(450, 650), random.uniform(-300, 300)
            p1 = Unit(GUNS[0], *find_land(x, Y0 + dy), "Player 1", 4)
            p2 = Unit(GUNS[0], *find_land(WORLD - x, Y0 - dy), "Player 2", 5)
            p1.az = math.degrees(math.atan2(p2.y - p1.y, p2.x - p1.x)) % 360
            p2.az = (p1.az + 180) % 360
            p2.flip = True
            self.units, self.targets = [p1, p2], []
            self.start_turn(0)
            self.say("Duel", 2)
        else:
            self.units = [Unit(GUNS[0], *(find_land_line if self.flat else find_land)(300, Y0))]
            self.spawn_targets()
            self.say("Sandbox")

    def continue_saved(self):
        save.load(self, self.saved)
        self.played, self.saved = True, None

    def autosave(self):
        """Save on quit, unless nothing happened (so a peek at the title keeps the old save)."""
        if not self.played:
            return
        try:
            save.save(self)
        except OSError:
            pass

    def start_turn(self, i):
        self.ui = i
        u = self.unit
        u.cooldown, u.fuel = 0.0, u.gun.fuel
        self.aim = self.entry = None
        self.turn_fired = False
        self.freecam = False
        self.input_mode = "move"
        if self.map_mode == 2:
            self.map_mode = 1
        self.new_wind()
        self.handover = True

    def new_wind(self):
        if not self.wind_on:
            self.wind = (0.0, 0.0)
            return
        a = random.uniform(0, 2 * math.pi)
        spd = random.uniform(0, WIND_MAX)
        self.wind = (spd * math.cos(a), 0.0 if self.flat else spd * math.sin(a))

    def drift_wind(self, rdt):
        """Sandbox: wind wanders slowly."""
        if not self.wind_on:
            return
        wx = self.wind[0] + random.gauss(0, 0.6) * rdt
        wy = 0.0 if self.flat else self.wind[1] + random.gauss(0, 0.6) * rdt
        spd = math.hypot(wx, wy)
        if spd > WIND_MAX:
            wx, wy = wx * WIND_MAX / spd, wy * WIND_MAX / spd
        self.wind = (wx, wy)

    def wind_text(self):
        if not self.wind_on:
            return "wind off"
        spd = math.hypot(*self.wind)
        wdir = math.degrees(math.atan2(self.wind[1], self.wind[0])) % 360
        return f"wind {spd:.1f}m/s to {wdir:.0f}deg"

    def open_menu(self, page):
        self.menu, self.menu_page = 0, page

    def end_turn(self):
        dead = [u for u in self.units if u.hp <= 0]
        if len(dead) == 2:
            self.winner = "DRAW - both guns destroyed"
        elif dead:
            alive = next(u for u in self.units if u.hp > 0)
            self.winner = f"{alive.name.upper()} WINS"
        else:
            self.start_turn(1 - self.ui)
        if self.winner:
            self.say(f"{self.winner}   {self.keys.label('new_targets')}: rematch", 1e9)

    def spawn_targets(self):
        u = self.units[0]
        if self.flat:           # everything on the line, east of the gun
            xs = [u.x + random.uniform(400, 2000) for _ in range(6)]
            xs += [u.x + random.uniform(3000, 9000) for _ in range(3)]
            self.targets = [Target(*find_land_line(x, u.y)) for x in xs]
            self.shots = 0
            return
        spots = [(u.x + random.uniform(400, 2000), u.y + random.uniform(-1000, 1000)) for _ in range(6)]
        for _ in range(3):      # far targets for the long-range guns
            a, r = random.uniform(-0.6, 0.6), random.uniform(3000, 9000)
            spots.append((u.x + r * math.cos(a), u.y + r * math.sin(a)))
        self.targets = [Target(*find_land(x, y)) for x, y in spots]
        self.shots = 0

    def change_type(self, d):
        u = self.unit
        u.set_gun(GUNS[(GUNS.index(u.gun) + d) % len(GUNS)])
        u.fuel = min(u.fuel, u.gun.fuel)

    def map_fit(self):
        """Full-map view [cx, cy, width] showing every explored chunk."""
        x0, y0, side = self.map_region()
        mw, mh = max(10, self.W - 2), max(5, self.H - 5)
        width = max(side, side * mw / (2 * mh)) * 1.05
        return [x0 + side / 2, y0 + side / 2, width]

    def fire(self):
        u = self.unit
        if u.cooldown > 0:
            self.say(f"Reloading ({u.cooldown:.1f}s)")
            return
        self.projectiles.append(u.make_projectile(self.wind))
        self.played = True
        u.cooldown = u.gun.reload
        self.shots += 1
        if self.duel:
            self.turn_fired = True

    # ---------------------------------------------------------- update
    def update(self, rdt):
        generate_pending(0.008)     # terrain in small slices per frame, never a long stall
        if self.menu is not None or self.title is not None or self.handover:
            return              # game paused while configuring / handing over
        self.msg_t -= rdt
        if not self.duel:
            self.drift_wind(rdt)
        for u in self.units:
            self.explore(u.x, u.y)
        for u in self.units:
            u.cooldown = max(0.0, u.cooldown - rdt)
        for e in self.explosions:
            e.ttl -= rdt
        self.explosions = [e for e in self.explosions if e.ttl > 0]
        self.acc += rdt * TIME_SCALE
        while self.acc >= DT:
            self.acc -= DT
            for p in self.projectiles:
                if p.result is None and p.step():
                    self.detonate(p)
            for p in self.projectiles:
                p.trail.append(p.pos)
                del p.trail[:-160]          # ~2 s of flight at normal speed
            self.projectiles = [p for p in self.projectiles if p.result is None]
        if (self.duel and self.turn_fired and not self.projectiles and not self.explosions
                and not self.winner):
            self.end_turn()

    def explore(self, x, y):
        c = chunk_of(x, y)
        if c not in self.explored:
            self.explored.add(c)
            self.map_cache = {}

    def map_region(self):
        """Square (x0, y0, side) covering the start area and every explored chunk."""
        xs = [0, WORLD] + [cx * CHUNK for cx, _ in self.explored] + [(cx + 1) * CHUNK for cx, _ in self.explored]
        ys = [0, WORLD] + [cy * CHUNK for _, cy in self.explored] + [(cy + 1) * CHUNK for _, cy in self.explored]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        side = max(x1 - x0, y1 - y0)
        return x0 - (side - (x1 - x0)) / 2, y0 - (side - (y1 - y0)) / 2, side

    def detonate(self, p):
        if p.result == "lost":
            self.say("Shell lost out of the map")
            self.report = f"{self.unit.name}: shell lost out of the map"
            return
        self.explosions.append(Explosion(p.pos, p.shell.blast))
        self.explore(p.x, p.y)
        # crater: full depth at ground level, none once burst height >= blast radius
        agl = p.z - height(p.x, p.y)
        depth = p.shell.crater * max(0.0, 1 - agl / p.shell.blast)
        if is_water(p.x, p.y):
            depth = 0           # splash: no crater in water
            if agl < 1:
                self.say("Splash!", 1.5)
        if depth > 0.5:
            make_crater(p.x, p.y, p.shell.blast, depth)
            self.map_cache = {}
        hits = 0
        for t in self.targets:
            if t.alive and math.dist(p.pos, (t.x, t.y, t.z)) <= p.shell.blast:
                t.alive = False
                hits += 1
        if hits:
            left = sum(t.alive for t in self.targets)
            self.say(f"HIT x{hits}!" + ("  All targets destroyed - n for more" if not left else ""))
        if self.duel:
            self.duel_damage(p)

    def duel_damage(self, p):
        shooter = self.unit
        enemy = self.units[1 - self.ui]
        parts = []
        for u in self.units:
            d = math.dist(p.pos, (u.x, u.y, u.z))
            if d <= p.shell.blast:
                dmg = round(p.shell.damage * (1 - 0.7 * d / p.shell.blast))
                u.hp = max(0, u.hp - dmg)
                parts.append(f"{u.name} hit -{dmg} HP ({u.hp} left)")
        if not parts:
            d = math.hypot(p.x - enemy.x, p.y - enemy.y)
            ds = math.hypot(p.x - shooter.x, p.y - shooter.y)
            de = math.hypot(enemy.x - shooter.x, enemy.y - shooter.y)
            parts.append(f"miss, {d:.0f} m from {enemy.name} ({'long' if ds > de else 'short'})")
        self.report = f"{shooter.name}: " + "; ".join(parts)
        self.say(self.report, 4)
