"""Understand a layout: which grid cells are solid, where hazards are, and how the level is paced."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

from . import objects as O
from .level import Level

Cell = tuple[int, int]


@dataclass
class Section:
    index: int
    x_start: float
    x_end: float
    mode: str
    intensity: float = 0.0  # 0 = calm, 1 = the busiest part of the level


@dataclass
class Layout:
    solid: set[Cell] = field(default_factory=set)
    slabs: set[Cell] = field(default_factory=set)
    hazards: set[Cell] = field(default_factory=set)
    busy: set[Cell] = field(default_factory=set)       # any gameplay object: keep particles out
    solid_objects: list[int] = field(default_factory=list)   # indices into level.objects
    hazard_objects: list[int] = field(default_factory=list)
    slab_objects: list[int] = field(default_factory=list)
    loose_objects: list[int] = field(default_factory=list)  # slopes and off-grid blocks: recolored only
    min_x: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    sections: list[Section] = field(default_factory=list)
    start_speed: int = 0
    speed_changes: list[tuple[float, int]] = field(default_factory=list)
    deco_object_count: int = 0

    # ---- time <-> x ------------------------------------------------------
    def x_at_time(self, t: float) -> float:
        """Player x position t seconds after the level starts (follows speed portals)."""
        x, speed, elapsed = 0.0, self.start_speed, 0.0
        for portal_x, new_speed in self.speed_changes:
            if portal_x <= x:
                speed = new_speed
                continue
            seg = (portal_x - x) / O.SPEED_UNITS_PER_SECOND[speed]
            if elapsed + seg >= t:
                break
            elapsed += seg
            x, speed = portal_x, new_speed
        return x + (t - elapsed) * O.SPEED_UNITS_PER_SECOND[speed]

    def time_at_x(self, target: float) -> float:
        x, speed, elapsed = 0.0, self.start_speed, 0.0
        for portal_x, new_speed in self.speed_changes:
            if portal_x >= target:
                break
            if portal_x > x:
                elapsed += (portal_x - x) / O.SPEED_UNITS_PER_SECOND[speed]
                x = portal_x
            speed = new_speed
        return elapsed + max(0.0, target - x) / O.SPEED_UNITS_PER_SECOND[speed]

    def section_at(self, x: float) -> Section:
        starts = [s.x_start for s in self.sections]
        return self.sections[max(0, bisect.bisect_right(starts, x) - 1)]

    def is_free(self, cell: Cell) -> bool:
        return cell not in self.solid and cell not in self.busy


def num(obj: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        return float(obj.get(key, default))
    except ValueError:
        return default


def scale_of(obj: dict[str, str]) -> tuple[float, float]:
    base = num(obj, O.SCALE, 1.0) or 1.0
    return num(obj, O.SCALE_X, base) or base, num(obj, O.SCALE_Y, base) or base


def _footprint(obj: dict[str, str], w: float, h: float) -> set[Cell]:
    """Cells whose centers lie inside the object's (axis-aligned, rotation-aware) box."""
    sx, sy = scale_of(obj)
    w, h = abs(w * sx), abs(h * sy)
    rot = num(obj, O.ROTATION) % 180
    if 45 < rot < 135:
        w, h = h, w
    x, y = num(obj, O.X), num(obj, O.Y)
    if w * h > 5000 * O.UNIT * O.UNIT:  # absurdly scaled object: don't enumerate millions of cells
        return {(math.floor(x / O.UNIT), math.floor(y / O.UNIT))}
    cells = set()
    i0, i1 = math.floor((x - w / 2) / O.UNIT), math.floor((x + w / 2 - 1e-6) / O.UNIT)
    j0, j1 = math.floor((y - h / 2) / O.UNIT), math.floor((y + h / 2 - 1e-6) / O.UNIT)
    for i in range(i0, i1 + 1):
        for j in range(j0, j1 + 1):
            cx, cy = i * O.UNIT + 15, j * O.UNIT + 15
            if abs(cx - x) <= w / 2 + 1e-6 and abs(cy - y) <= h / 2 + 1e-6:
                cells.add((i, j))
    if not cells:
        cells.add((math.floor(x / O.UNIT), math.floor(y / O.UNIT)))
    return cells


def _on_grid(obj: dict[str, str]) -> bool:
    """True for a block that exactly fills whole grid cells (so a grid-aligned overlay covers it)."""
    if obj.get(O.Z_LAYER, "0") in (str(O.T2), str(O.T3), str(O.T4)):
        return False  # drawn above our overlay layer
    rot = num(obj, O.ROTATION) % 90
    if min(rot, 90 - rot) > 0.01:
        return False
    sx, sy = (abs(s) for s in scale_of(obj))
    if (num(obj, O.ROTATION) % 180) > 45:
        sx, sy = sy, sx
    left, bottom = num(obj, O.X) - 15 * sx, num(obj, O.Y) - 15 * sy

    def whole(v: float) -> bool:
        return abs(v - round(v)) < 0.01

    return whole(sx) and whole(sy) and whole(left / O.UNIT) and whole(bottom / O.UNIT)


def analyze(level: Level, section_blocks: tuple[int, int] = (24, 90)) -> Layout:
    """Build a :class:`Layout` from a level.

    ``section_blocks`` is (min, max) section length in blocks: gamemode changes start
    new sections, and very long stretches are split so colors keep evolving.
    """
    lay = Layout()
    speed = int(num(level.header, "kA4", 0))
    lay.start_speed = speed if speed in O.SPEED_UNITS_PER_SECOND else 0
    mode = int(num(level.header, "kA2", 0))
    start_mode = O.GAMEMODES[mode] if 0 <= mode < len(O.GAMEMODES) else "cube"

    mode_changes: list[tuple[float, str]] = []
    xs: list[float] = []
    ys: list[float] = []
    density_points: list[float] = []

    for idx, obj in enumerate(level.objects):
        try:
            oid = int(obj.get(O.ID, "0"))
        except ValueError:
            continue
        x, y = num(obj, O.X), num(obj, O.Y)
        gameplay = True
        if oid in O.SOLID_BLOCKS and _on_grid(obj):
            lay.solid |= _footprint(obj, 30, 30)
            lay.solid_objects.append(idx)
        elif oid in O.SOLID_BLOCKS or oid in O.SLOPES:
            lay.busy |= _footprint(obj, 30, 30)
            lay.loose_objects.append(idx)
        elif oid in O.SLABS:
            lay.slabs |= _footprint(obj, 30, 30)
            lay.busy |= _footprint(obj, 30, 30)
            lay.slab_objects.append(idx)
        elif oid in O.HAZARDS:
            cells = _footprint(obj, 30, 30)
            lay.hazards |= cells
            lay.busy |= cells
            lay.hazard_objects.append(idx)
            density_points.append(x)
        elif oid in O.ORBS_AND_PADS:
            lay.busy |= _footprint(obj, 36, 36)
            density_points.append(x)
        elif oid in O.GAMEMODE_PORTALS or oid in O.OTHER_PORTALS or oid in O.SPEED_PORTALS:
            lay.busy |= _footprint(obj, 36, 90)
            if oid in O.GAMEMODE_PORTALS:
                mode_changes.append((x, O.GAMEMODE_PORTALS[oid]))
            if oid in O.SPEED_PORTALS:
                lay.speed_changes.append((x, O.SPEED_PORTALS[oid]))
        elif oid in (O.COLOR_TRIGGER, O.PULSE_TRIGGER) or oid == O.START_POS:
            gameplay = False
        else:
            gameplay = False
            lay.deco_object_count += 1
        if gameplay:
            xs.append(x)
            ys.append(y)

    lay.speed_changes.sort()
    lay.min_x = min(xs, default=0.0)
    lay.max_x = max(xs, default=O.UNIT * 40)
    # Height of the play area: ignore the top 1% so a few far-away objects don't stretch the decoration.
    ys.sort()
    lay.max_y = ys[int(0.99 * (len(ys) - 1))] if ys else O.UNIT * 10
    lay.sections = _sections(lay, start_mode, sorted(mode_changes), sorted(density_points), section_blocks)
    return lay


def _sections(lay: Layout, start_mode: str, mode_changes, density_points, section_blocks) -> list[Section]:
    min_len, max_len = section_blocks[0] * O.UNIT, section_blocks[1] * O.UNIT
    end = lay.max_x + 10 * O.UNIT
    bounds: list[tuple[float, str]] = [(0.0, start_mode)]
    for x, mode in mode_changes:
        if mode == bounds[-1][1]:
            continue
        if x - bounds[-1][0] < min_len:
            bounds[-1] = (bounds[-1][0], mode)  # too short for its own colors: relabel the current one
        else:
            bounds.append((x, mode))
    # Split long stretches evenly.
    split: list[tuple[float, str]] = []
    for k, (x, mode) in enumerate(bounds):
        nxt = bounds[k + 1][0] if k + 1 < len(bounds) else end
        pieces = max(1, math.ceil((nxt - x) / max_len))
        for p in range(pieces):
            split.append((x + (nxt - x) * p / pieces, mode))
    sections = []
    for k, (x, mode) in enumerate(split):
        nxt = split[k + 1][0] if k + 1 < len(split) else end
        sections.append(Section(k, x, nxt, mode))
    # Intensity = interactive/hazard objects per block, ranked across sections.
    rates = []
    for s in sections:
        n = bisect.bisect_left(density_points, s.x_end) - bisect.bisect_left(density_points, s.x_start)
        rates.append(n / max(1.0, (s.x_end - s.x_start) / O.UNIT))
    hi = max(rates, default=0) or 1.0
    for s, r in zip(sections, rates):
        s.intensity = round(r / hi, 3)
    return sections
