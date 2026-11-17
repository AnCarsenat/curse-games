"""Tunable constants shared by every module."""


# ------------------------------------------------------------------ constants
G = 9.81            # gravity m/s^2
WORLD = 2400.0      # starting area (m); the world is endless, generated in chunks
Y0 = WORLD / 2      # starting line of the units
CHUNK = 400.0       # terrain damage and the minimap grow in chunks of CHUNK x CHUNK m
SEA = 0.0           # water level (m): terrain below it is lake/sea
RELIEFS = [1.0, 1.5, 2.5, 4.0]   # vertical exaggeration of the side view (game settings)
DT = 0.05           # physics step (s)
TIME_SCALE = 4.0    # simulated seconds per real second
MAX_FLIGHT = 120.0  # shells older than this are discarded
WIND_PUSH = 0.03    # lateral acceleration (m/s^2) per m/s of wind
WIND_MAX = 8.0      # max wind speed (m/s); duel rerolls every turn, sandbox drifts
DUEL_HP = 100
MOVE_BUDGET = 150.0  # duel: default metres a mobile unit may drive per turn
VIEW_SPANS = [2200.0, 4400.0, 8800.0, 17600.0]   # widths of the side view (game settings)
AIM_STEPS = [10.0, 1.0, 0.1, 0.01]             # precision steps of the aiming dial (deg)


MODES = [("sandbox", "Sandbox", "free fire at targets, terrain repair"),
         ("duel", "Duel", "1v1 pass and play on one keyboard, one shot per turn")]
