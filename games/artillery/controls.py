"""Keyboard handling for the main view, aiming dial, map, menus and title screen."""
import curses
import math

from .config import AIM_STEPS, MODES, RELIEFS, VIEW_SPANS
from .world import WORLD_TYPES, ground, is_water, reset_terrain
from .content import GUNS, SHELLS
from .keys import ACTIONS, BACKSPACE_CODES, ENTER_CODES, GUN_ACTIONS, LAYOUTS


class ControlsMixin:
    # ---------------------------------------------------------- input
    def key(self, k):
        act = self.keys.action(k)
        if self.help and (k == 27 or act == "help"):
            self.help = False
            return True
        if self.title is not None:
            return self.title_key(k, act)
        if self.menu is not None:
            return self.menu_key(k, act)
        u, gun = self.unit, self.unit.gun
        if act == "quit":
            return False
        if self.winner:
            if act == "new_targets":
                self.new_game("duel")
            elif act == "menu":
                self.open_menu("game")
            elif act == "help":
                self.help = not self.help
            return True
        if self.handover:
            if act == "fire" or k in ENTER_CODES:
                self.handover = False
                self.say(f"{u.name}: aim and fire", 2)
            elif act in ("menu", "gun_menu"):
                self.open_menu("game" if act == "menu" else "gun")
            elif act == "help":
                self.help = not self.help
            return True
        if self.aim is not None:
            return self.aim_key(k, act)
        if self.map_mode == 2:
            return self.map_key(k, act)
        if (self.duel and self.turn_fired and act in GUN_ACTIONS
                and not (self.freecam and act in ("left", "right", "forward", "back"))):
            self.say("Shot in the air - wait for the impact")
            return True
        if act in ("menu", "gun_menu"):
            self.open_menu("game" if act == "menu" else "gun")
        elif act == "aim_gui":
            self.aim = "pitch"
        elif act == "help":
            self.help = not self.help
        elif act in ("elev_up", "elev_down", "elev_up5", "elev_down5"):
            mult = {"elev_up": 1, "elev_down": -1, "elev_up5": 10, "elev_down5": -10}[act]
            u.elev = round(u.elev + mult * AIM_STEPS[self.aim_step], 2)
        elif act in ("step_up", "step_down"):
            self.aim_step = max(0, min(len(AIM_STEPS) - 1, self.aim_step + (-1 if act == "step_up" else 1)))
            self.say(f"Aim step {AIM_STEPS[self.aim_step]:g} deg", 1.5)
        elif act == "map":
            self.map_mode = (self.map_mode + 1) % 3
            if self.map_mode == 2:
                self.mapview = self.map_fit()
        elif act == "fire":
            self.fire()
        elif act == "charge_next":
            u.ci = (u.ci + 1) % len(gun.charges)
        elif act == "charge_prev":
            u.ci = (u.ci - 1) % len(gun.charges)
        elif act == "shell_next":
            u.si = (u.si + 1) % len(gun.shells)
            u.fuse_time = u.shell.fuse_time
            self.say(f"Loaded {u.shell.name}")
        elif act in ("fuse_down", "fuse_up"):
            if u.shell.fuse == "timed":
                u.fuse_time = max(0.5, u.fuse_time + (0.5 if act == "fuse_up" else -0.5))
            else:
                self.say(f"{u.shell.name} has a {u.shell.fuse} fuse, no timer")
        elif act == "unit_type":
            self.change_type(1)
            self.say(f"Unit type: {u.gun.name}")
        elif act == "graph":
            self.graph = (self.graph + 1) % 4
        elif act == "freecam":
            self.freecam = not self.freecam
            self.cam = [u.x, u.y, (u.az + 180) % 360 if u.flip else u.az]
            self.say("Free camera" if self.freecam else "Camera follows unit")
        elif act == "new_targets":
            if self.duel:
                self.say(f"Duel in progress ({self.keys.label('menu')} > Game mode to restart)")
            else:
                self.spawn_targets()
                self.new_wind()
                self.say("New targets, new wind")
        elif act == "repair":
            if self.duel:
                self.say("No terrain repair in a duel")
                return True
            reset_terrain()
            self.map_cache = {}
            self.say("Terrain repaired")
        elif act == "gauge":
            self.gauge = not self.gauge
        elif act in ("left", "right", "forward", "back"):
            self.move(act)
        u.elev = max(gun.elev_min, min(gun.elev_max, u.elev))
        return True

    def aim_key(self, k, act):
        u, g = self.unit, self.unit.gun
        step = AIM_STEPS[self.aim_step]
        d = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1, curses.KEY_NPAGE: -10,
             curses.KEY_PPAGE: 10}.get(k) or {"left": -1, "right": 1}.get(act)
        if act == "quit":
            return False
        if k == 27 or k in ENTER_CODES or act == "aim_gui":
            self.aim = None
        elif k == 9:
            self.aim = "yaw" if self.aim == "pitch" else "pitch"
        elif k == curses.KEY_UP or act in ("forward", "step_up"):
            self.aim_step = max(0, self.aim_step - 1)
        elif k == curses.KEY_DOWN or act in ("back", "step_down"):
            self.aim_step = min(len(AIM_STEPS) - 1, self.aim_step + 1)
        elif act == "help":
            self.help = not self.help
        elif act == "fire":
            if self.duel and self.turn_fired:
                self.say("Shot in the air - wait for the impact")
            else:
                self.fire()
        elif d:
            if self.duel and self.turn_fired:
                self.say("Shot in the air - wait for the impact")
            elif self.aim == "pitch":
                u.elev = round(max(g.elev_min, min(g.elev_max, u.elev + d * step)), 2)
            else:
                u.az = round((u.az + d * step) % 360, 2)
        return True

    def map_key(self, k, act):
        cx, cy, width = self.mapview
        pan = width / 8
        if act == "quit":
            return False
        if k == 27 or k in ENTER_CODES:
            self.map_mode = 1
        elif act == "map":
            self.map_mode = 0
        elif k == curses.KEY_LEFT or act == "left":
            cx -= pan
        elif k == curses.KEY_RIGHT or act == "right":
            cx += pan
        elif k == curses.KEY_UP or act == "forward":
            cy += pan
        elif k == curses.KEY_DOWN or act == "back":
            cy -= pan
        elif act == "step_up" or k in (curses.KEY_PPAGE, ord("+"), ord("=")):
            width = max(250.0, width / 2)
        elif act == "step_down" or k in (curses.KEY_NPAGE, ord("-")):
            width = min(64000.0, width * 2)
        elif k in (curses.KEY_HOME, ord("0")):
            cx, cy, width = self.map_fit()
        elif k == ord("u"):
            cx, cy = self.unit.x, self.unit.y
        elif act == "help":
            self.help = not self.help
        elif act == "fire":
            if self.duel and self.turn_fired:
                self.say("Shot in the air - wait for the impact")
            else:
                self.fire()
        self.mapview = [cx, cy, width]
        return True

    def title_key(self, k, act):
        if act == "quit":
            return False
        if k == 27:
            self.title = None
        elif k == curses.KEY_UP or act == "forward":
            self.title = (self.title - 1) % len(MODES)
        elif k == curses.KEY_DOWN or act == "back":
            self.title = (self.title + 1) % len(MODES)
        elif k in (curses.KEY_LEFT, curses.KEY_RIGHT) or act in ("left", "right"):
            d = 1 if k == curses.KEY_RIGHT or act == "right" else -1
            self.world_type = (self.world_type + d) % len(WORLD_TYPES)
        elif k in ENTER_CODES or act == "fire" or ord("1") <= k < ord("1") + len(MODES):
            if ord("1") <= k < ord("1") + len(MODES):
                self.title = k - ord("1")
            self.new_game(MODES[self.title][0])
            self.title = None
        return True

    def move(self, act):
        u = self.unit
        if self.freecam:
            a = math.radians(self.cam[2])
            if act == "left":
                self.cam[2] = (self.cam[2] + 3) % 360
            elif act == "right":
                self.cam[2] = (self.cam[2] - 3) % 360
            else:
                d = 40 if act == "forward" else -40
                self.cam[0] += math.cos(a) * d
                self.cam[1] += math.sin(a) * d
            return
        if act in ("left", "right"):    # left = counter-clockwise on the map
            step = AIM_STEPS[self.aim_step]
            u.az = round((u.az + (step if act == "left" else -step)) % 360, 2)
            return
        direction = 1 if act == "forward" else -1
        if not u.gun.mobile:
            self.say(f"{u.gun.name} cannot drive ({self.keys.label('unit_type')}: change unit type)")
            return
        a = math.radians(u.az)     # forward = along the gun heading
        nx = u.x + direction * math.cos(a) * u.gun.speed
        ny = u.y + direction * math.sin(a) * u.gun.speed
        if is_water(nx, ny):
            self.say("Water ahead - cannot drive there")
            return
        if ground(nx, ny) - ground(u.x, u.y) > 0.8 * u.gun.speed:
            self.say("Too steep to climb")
            return
        if self.duel:
            if u.fuel < u.gun.speed:
                self.say("No fuel left this turn")
                return
            u.fuel -= u.gun.speed
        u.x, u.y = nx, ny

    # ---------------------------------------------------------- config menu
    def menu_rows(self):
        """(label, value text, change(delta) or None). Add rows to expose more settings."""
        u, g = self.unit, self.unit.gun

        def set_unit(d):
            if self.duel and (self.turn_fired or self.winner):
                return
            self.change_type(d)

        def set_shell(d):
            u.si = (u.si + d) % len(g.shells)
            u.fuse_time = u.shell.fuse_time

        def set_charge(d):
            u.ci = (u.ci + d) % len(g.charges)

        def set_fuse(d):
            u.fuse_time = max(0.5, u.fuse_time + 0.5 * d)

        def set_elev(d):
            u.elev = max(g.elev_min, min(g.elev_max, u.elev + d))

        def set_heading(d):
            u.az = (u.az - d) % 360

        def set_graph(d):
            self.graph = (self.graph + d) % 4

        def set_gauge(d):
            self.gauge = not self.gauge

        def set_layout(d):
            ids = list(LAYOUTS)
            self.keys.set_layout(ids[(ids.index(self.keys.layout) + d) % len(ids)])

        def open_keys(d):
            self.keymenu = 0

        def open_modes(d):
            self.menu = None
            self.title = [m for m, _, _ in MODES].index(self.mode)

        def set_minimap(d):
            self.map_mode = 0 if self.map_mode else 1

        def set_world(d):
            self.world_type = (self.world_type + d) % len(WORLD_TYPES)

        def set_relief(d):
            self.relief_i = (self.relief_i + d) % len(RELIEFS)

        def set_span(d):
            self.span_i = (self.span_i + d) % len(VIEW_SPANS)

        def set_wind(d):
            self.wind_on = not self.wind_on
            self.new_wind()

        if self.menu_page == "game":
            return [
                ("Game mode", f"{dict((m, n) for m, n, _ in MODES)[self.mode]} - Enter to change", open_modes),
                ("World type", WORLD_TYPES[self.world_type][1] + (
                    "  - Enter: new world" if self.world_type != self.world_now else "  (current)"),
                 set_world),
                ("Wind", ("on, " + self.wind_text()) if self.wind_on else "off", set_wind),
                ("Graph", ["off", "range", "time of flight", "firing table"][self.graph], set_graph),
                ("View width", f"{VIEW_SPANS[self.span_i] / 1000:g} km", set_span),
                ("Relief", f"x{RELIEFS[self.relief_i]:g} vertical exaggeration", set_relief),
                ("Gauge", "on" if self.gauge else "off", set_gauge),
                ("Minimap", "on" if self.map_mode else "off", set_minimap),
                ("Layout", LAYOUTS[self.keys.layout][0], set_layout),
                ("Key bindings", "Enter to edit", open_keys),
            ]
        timed = u.shell.fuse == "timed"
        return [
            ("Unit type", f"{GUNS.index(g) + 1}/{len(GUNS)} {g.char} {g.name}", set_unit),
            ("Shell", f"{u.shell.name} ({u.shell.fuse} fuse)", set_shell),
            ("Charge", f"{u.charge.name} - {u.charge.velocity:.0f} m/s", set_charge),
            ("Fuse time", f"{u.fuse_time:.1f} s" if timed else "- (no timer on this fuse)",
             set_fuse if timed else None),
            ("Elevation", f"{u.elev:.2f} deg  (limits {g.elev_min:.0f}-{g.elev_max:.0f})", set_elev),
            ("Heading", f"{u.az:.2f} deg", set_heading),
        ]

    def menu_info(self):
        if self.menu_page == "game":
            _, name, desc, _, _ = WORLD_TYPES[self.world_type]
            return [f"World type {name}: {desc}",
                    "Enter on World type generates a new world (restarts the game).",
                    f"Gun settings: {self.keys.label('gun_menu')}   Tab: switch page"]
        u, g, sh = self.unit, self.unit.gun, self.unit.shell
        yn = lambda b: "yes" if b else "no"
        charges = "  ".join(("[%s:%.0f]" if i == u.ci else " %s:%.0f ") % (c.name, c.velocity)
                            for i, c in enumerate(g.charges))
        shells = "  ".join(("[%s]" if i == u.si else " %s ") % SHELLS[k].name
                           for i, k in enumerate(g.shells))
        return [
            f"mobile {yn(g.mobile)}   fire control {yn(g.prediction)}   sight {yn(g.sight)}"
            f"   reload {g.reload:.1f} s",
            f"charges (m/s): {charges}",
            f"shells: {shells}",
            f"{sh.name}: blast {sh.blast:.0f} m, crater {sh.crater:.0f} m, drag {sh.drag:g}",
            f"Game settings: {self.keys.label('menu')}   Tab: switch page",
        ]

    def menu_key(self, k, act):
        up = k == curses.KEY_UP or act == "forward"
        down = k == curses.KEY_DOWN or act == "back"
        enter = k in (10, 13, curses.KEY_ENTER)
        esc = k == 27
        if self.keymenu is not None:
            return self.keymenu_key(k, up, down, enter, esc, act)
        rows = self.menu_rows()
        label, _, change = rows[self.menu]
        if enter and label in ("Key bindings", "Game mode"):
            change(1)
        elif enter and label == "World type":
            self.menu = None
            self.new_game(self.mode)
            self.say(f"New {WORLD_TYPES[self.world_type][1].lower()} world")
        elif k == 9:
            self.open_menu("gun" if self.menu_page == "game" else "game")
        elif esc or enter or act == "quit":
            self.menu = None
        elif act in ("menu", "gun_menu"):
            page = "game" if act == "menu" else "gun"
            if page == self.menu_page:
                self.menu = None
            else:
                self.open_menu(page)
        elif up:
            self.menu = (self.menu - 1) % len(rows)
        elif down:
            self.menu = (self.menu + 1) % len(rows)
        else:
            d = {curses.KEY_LEFT: -1, curses.KEY_RIGHT: 1,
                 curses.KEY_NPAGE: -5, curses.KEY_PPAGE: 5}.get(k) or {"left": -1, "right": 1}.get(act)
            if d and change:
                change(d)
        return True

    def keymenu_key(self, k, up, down, enter, esc, act):
        action, desc = ACTIONS[self.keymenu]
        if self.capturing:
            self.capturing = False
            if not esc:
                self.keys.bind(action, k)
                self.say(f"{desc}: {self.keys.label(action)}")
        elif esc or act == "menu":
            self.keymenu = None
        elif up:
            self.keymenu = (self.keymenu - 1) % len(ACTIONS)
        elif down:
            self.keymenu = (self.keymenu + 1) % len(ACTIONS)
        elif enter:
            self.capturing = True
        elif k in BACKSPACE_CODES or k == curses.KEY_DC:
            self.keys.reset(action)
        return True
