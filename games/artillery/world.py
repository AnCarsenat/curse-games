"""Endless terrain: seeded value-noise generation cached per chunk, craters, lakes."""
import math
import random
import time

from .config import CHUNK, SEA


# ------------------------------------------------------------------ world generation
# Seeded value noise. Large scale "macro" noise decides the landscape type
# (lakes and plains where low, rolling hills in between, ridged mountains where
# high); fractal noise adds hills and detail on top.
_seed = 0
_M = 0xFFFFFFFF


def _noise(x, y, s):
    """Smooth value noise in 0..1 with a feature size of 1 unit (hash inlined for speed)."""
    ix = int(x)
    if ix > x:
        ix -= 1
    iy = int(y)
    if iy > y:
        iy -= 1
    fx, fy = x - ix, y - iy
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    x0 = ix * 374761393 + s * 1442695041
    x1 = x0 + 374761393
    y0 = iy * 668265263
    y1 = y0 + 668265263
    h = (x0 + y0) & _M
    h = ((h ^ (h >> 13)) * 1274126177) & _M
    a = (h ^ (h >> 16)) & 0xFFFF
    h = (x1 + y0) & _M
    h = ((h ^ (h >> 13)) * 1274126177) & _M
    b = (h ^ (h >> 16)) & 0xFFFF
    h = (x0 + y1) & _M
    h = ((h ^ (h >> 13)) * 1274126177) & _M
    c = (h ^ (h >> 16)) & 0xFFFF
    h = (x1 + y1) & _M
    h = ((h ^ (h >> 13)) * 1274126177) & _M
    d = (h ^ (h >> 16)) & 0xFFFF
    return (a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy) * (1 / 65535)


_HILL_OCTAVES = [(1100.0 / 2.3 ** o, 0.5 ** o / 1.875) for o in range(4)]   # (wavelength, weight)


def _layered(x, y, detail, P):
    """Generic landscape: macro noise picks lowland / hills / mountains, fractal
    noise adds hills, ridged noise makes mountain ranges. P = preset parameters."""
    s = _seed
    n = _noise
    macro = 0.6 * n(x / 7000, y / 7000, s) + 0.4 * n(x / 2600, y / 2600, s + 1)
    macro = min(1.0, max(0.0, (macro - 0.5) * 2.2 + 0.5 + P["bias"]))   # spread out
    hills = 0.0                                             # -0.5..0.5
    for o, (wl, w) in enumerate(_HILL_OCTAVES):
        if wl < detail:
            break
        hills += w * (n(x / wl, y / wl, s + 2 + o) - 0.5)
    h = P["base"] + P["macro"] * macro + P["hills"] * hills * (0.25 + 1.2 * abs(macro - 0.4))
    m0 = P["mount_at"]
    if macro > m0:                                          # mountain regions: ridges
        mount = ((macro - m0) / (1 - m0)) ** 1.5
        ridge = 1 - abs(2 * n(x / 1500, y / 1500, s + 8) - 1)
        ridge2 = 0.5 if detail > 550 else 1 - abs(2 * n(x / 550, y / 550, s + 9) - 1)
        h += mount * P["ridges"] * (ridge * ridge + 0.27 * ridge2 * ridge)
    if 0 < h < 25:                                          # flatten shores into beaches
        h = h * h / 25
    return h


def _canyons(x, y, detail, P):
    """High plateau cut by narrow winding canyons with rivers at the bottom."""
    s, n = _seed, _noise
    plateau = 170 + 90 * n(x / 3000, y / 3000, s) + 30 * (n(x / 400, y / 400, s + 1) - 0.5)
    cut = 1 - abs(2 * n(x / 1800, y / 1800, s + 2) - 1)     # 1 along the canyon lines
    cut2 = 1 - abs(2 * n(x / 700, y / 700, s + 3) - 1)
    depth = max(cut ** 8, 0.6 * cut2 ** 10)
    h = plateau - depth * (plateau + 25)
    return h if h < 0 else round(h / 6) * 6 * 0.4 + h * 0.6   # slight terracing


def _dunes(x, y, detail, P):
    """Desert: long parallel dunes with a few rocky outcrops, no water."""
    s, n = _seed, _noise
    a = 0.5 * n(x / 5000, y / 5000, s)                      # dune direction drifts slowly
    u = x * math.cos(a) + y * math.sin(a)
    v = -x * math.sin(a) + y * math.cos(a)
    crest = 0.0 if detail > 150 else abs(2 * n(u / 140, v / 900, s + 1) - 1)
    dune = (1 - crest) ** 2 * 45                             # sharp crests, wide troughs
    rock = max(0.0, n(x / 1200, y / 1200, s + 2) - 0.7) * 600
    return 60 + 60 * n(x / 4000, y / 4000, s + 3) + dune + rock


def _flat(x, y, detail, P):
    return 50.0


def _classic(x, y, detail, P):
    """The original rolling sine hills."""
    return (120 + 40 * math.sin(x / 170) + 25 * math.sin(x / 67 + 1.3)
            + 30 * math.sin(y / 210 + 0.5) + 20 * math.sin((x + y) / 120))


_MIXED = {"bias": 0.0, "base": -60, "macro": 330, "hills": 220, "mount_at": 0.58, "ridges": 520}
WORLD_TYPES = [   # (id, name, description, shape function, parameters)
    ("mixed", "Mixed", "plains, hills, mountain ranges and lakes", _layered, _MIXED),
    ("plains", "Plains", "wide open lowland, gentle rises, small ponds", _layered,
     dict(_MIXED, base=5, macro=110, hills=110, mount_at=2.0)),
    ("hills", "Hills", "rolling hills everywhere, few lakes", _layered,
     dict(_MIXED, base=20, macro=190, hills=480, mount_at=0.85, ridges=300)),
    ("mountains", "Mountains", "high ridges and deep valleys", _layered,
     dict(_MIXED, bias=0.15, base=-20, macro=300, hills=260, mount_at=0.35, ridges=760)),
    ("islands", "Islands", "archipelago: mostly water, steep islands", _layered,
     dict(_MIXED, bias=-0.2, base=-190, macro=420, hills=200, mount_at=0.7, ridges=420)),
    ("canyons", "Canyons", "high plateau cut by narrow river canyons", _canyons, None),
    ("dunes", "Dunes", "desert of long dunes and rocky outcrops", _dunes, None),
    ("flat", "Flat", "perfectly flat ground (testing)", _flat, None),
    ("classic", "Classic", "the original repeating sine hills", _classic, None),
]
_shape, _params = _layered, _MIXED


def raw_height(x, y, detail=0.0):
    """Undamaged terrain altitude straight from the generator (slow, see base_height).
    `detail` (m): skip noise layers finer than that (maps drawn zoomed out)."""
    return _shape(x, y, detail, _params)


# Base terrain is sampled on a BASE_CELL grid per chunk on first use, then interpolated.
BASE_CELL = 20.0
BASE_N = int(CHUNK / BASE_CELL)
_base_chunks = {}


def base_height(x, y):
    """Undamaged terrain altitude at (x, y) (may be below SEA)."""
    fx, fy = x / BASE_CELL, y / BASE_CELL
    ix, iy = math.floor(fx), math.floor(fy)
    tx, ty = fx - ix, fy - iy
    key = (ix // BASE_N, iy // BASE_N)
    c = _base_chunks.get(key)
    if c is None:   # (BASE_N + 1)^2 samples: the extra row/column overlaps the next chunk
        c = _gen_chunk(key)
    i, j = ix % BASE_N, iy % BASE_N
    c0, c1 = c[i], c[i + 1]
    return ((c0[j] * (1 - ty) + c0[j + 1] * ty) * (1 - tx)
            + (c1[j] * (1 - ty) + c1[j + 1] * ty) * tx)


_pending = set()   # chunks the view wants; generated a little per frame
_partial = {}      # chunk -> columns generated so far (background generation)


def _column(bx, by, i):
    return [raw_height((bx + i) * BASE_CELL, (by + j) * BASE_CELL) for j in range(BASE_N + 1)]


def _gen_chunk(key):
    """Finish generating a chunk now (blocking), reusing any columns already made."""
    bx, by = key[0] * BASE_N, key[1] * BASE_N
    c = _partial.pop(key, [])
    for i in range(len(c), BASE_N + 1):
        c.append(_column(bx, by, i))
    _base_chunks[key] = c
    _pending.discard(key)
    return c


def view_height(x, y):
    """Like base_height, but never blocks: an ungenerated chunk is queued and the
    noise is sampled directly meanwhile."""
    key = (math.floor(x / CHUNK), math.floor(y / CHUNK))
    if key in _base_chunks:
        return base_height(x, y)
    _pending.add(key)
    return raw_height(x, y)


def view_surface(x, y):
    """Non-blocking surface altitude (for predictions drawn on screen)."""
    return max(SEA, view_height(x, y) + deform(x, y))


def chunks_ready():
    return len(_base_chunks)


def generate_pending(budget):
    """Generate queued chunks for up to `budget` seconds, one column at a time
    (a whole chunk takes longer than a frame)."""
    end = time.perf_counter() + budget
    while _pending and time.perf_counter() < end:
        key = next(iter(_pending))
        if key in _base_chunks:
            _pending.discard(key)
            continue
        cols = _partial.setdefault(key, [])
        bx, by = key[0] * BASE_N, key[1] * BASE_N
        while len(cols) <= BASE_N and time.perf_counter() < end:
            cols.append(_column(bx, by, len(cols)))
        if len(cols) > BASE_N:
            _gen_chunk(key)


def new_world(seed, world_type=0):
    """Start a fresh world from a seed and an index into WORLD_TYPES."""
    global _seed, _shape, _params
    _seed = seed
    _, _, _, _shape, _params = WORLD_TYPES[world_type]
    _base_chunks.clear()
    _pending.clear()
    _partial.clear()
    reset_terrain()
    # map shading bands follow this world's own height range (dunes vs mountains)
    rng = random.Random(seed)
    land = sorted(h for h in (raw_height(rng.uniform(-8000, 8000), rng.uniform(-8000, 8000))
                              for _ in range(300)) if h >= SEA)
    if land:
        lo, hi = land[len(land) // 20], land[-1 - len(land) // 50]
        _shade[:] = [lo, max(4.0, (hi - lo) / 7)]


_shade = [0.0, 120.0]   # (lowest band altitude, band height) for map shading


def shade_level(h):
    """Map shading band 0..6 of a dry-land altitude."""
    return min(6, max(0, int((h - _shade[0]) / _shade[1])))


# Terrain damage: height offsets (m) on a CELL grid, bilinearly interpolated,
# stored in chunks that are only created when a crater touches them.
CELL = 10.0
CHUNK_CELLS = int(CHUNK / CELL)
terrain_version = [0]   # bumped on every terrain change (prediction cache key)
_chunks = {}   # (chunk_x, chunk_y) -> [[offset] * CHUNK_CELLS] * CHUNK_CELLS, indexed [ix][iy]


def chunk_of(x, y):
    return math.floor(x / CHUNK), math.floor(y / CHUNK)


def _cell(ix, iy):
    c = _chunks.get((ix // CHUNK_CELLS, iy // CHUNK_CELLS))
    return c[ix % CHUNK_CELLS][iy % CHUNK_CELLS] if c else 0.0


def _cell_add(ix, iy, v):
    key = (ix // CHUNK_CELLS, iy // CHUNK_CELLS)
    c = _chunks.get(key)
    if c is None:
        c = _chunks[key] = [[0.0] * CHUNK_CELLS for _ in range(CHUNK_CELLS)]
    c[ix % CHUNK_CELLS][iy % CHUNK_CELLS] += v


def deform(x, y):
    fx, fy = x / CELL, y / CELL
    ix, iy = math.floor(fx), math.floor(fy)
    if not _chunks:
        return 0.0
    tx, ty = fx - ix, fy - iy
    return ((_cell(ix, iy) * (1 - ty) + _cell(ix, iy + 1) * ty) * (1 - tx)
            + (_cell(ix + 1, iy) * (1 - ty) + _cell(ix + 1, iy + 1) * ty) * tx)


def ground(x, y):
    """Terrain altitude including craters; below SEA means under water."""
    return base_height(x, y) + deform(x, y)


def height(x, y):
    """Surface altitude at (x, y): ground, or the water surface over lakes."""
    return max(SEA, base_height(x, y) + deform(x, y))


def is_water(x, y):
    return ground(x, y) < SEA


def find_land(x, y):
    """Nearest dry, not too steep spot to (x, y), searching outwards. Samples the
    noise directly so the search never generates terrain chunks."""
    def g(px, py):
        return raw_height(px, py) + deform(px, py)
    r = 0.0
    while r < 8000:
        count = max(1, int(2 * math.pi * r / 80))
        for k in range(count):
            a = 2 * math.pi * k / count
            px, py = x + r * math.cos(a), y + r * math.sin(a)
            h = g(px, py)
            if h > SEA + 3 and abs(g(px + 15, py) - h) < 12 and abs(g(px, py + 15) - h) < 12:
                return px, py
        r += 40 if r < 1000 else 150
    return x, y


def find_land_line(x, y):
    """Like find_land, but only searches along the x axis (2D games stay on y)."""
    def g(px):
        return raw_height(px, y) + deform(px, y)
    for d in range(0, 8000, 20):
        for px in ((x + d, x - d) if d else (x,)):
            h = g(px)
            if h > SEA + 3 and abs(g(px + 15) - h) < 12:
                return px, y
    return x, y


def make_crater(x, y, radius, depth):
    """Dig a bowl of `radius` and `depth` with a small raised rim."""
    rim = radius * 1.4
    terrain_version[0] += 1
    for ix in range(math.floor((x - rim) / CELL), math.floor((x + rim) / CELL) + 2):
        for iy in range(math.floor((y - rim) / CELL), math.floor((y + rim) / CELL) + 2):
            d = math.hypot(ix * CELL - x, iy * CELL - y)
            if d < radius:
                _cell_add(ix, iy, -depth * (1 - (d / radius) ** 2))
            elif d < rim:
                _cell_add(ix, iy, depth * 0.25 * math.sin(math.pi * (d - radius) / (rim - radius)))


def reset_terrain():
    _chunks.clear()
    terrain_version[0] += 1
