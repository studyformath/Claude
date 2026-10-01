"""The decoration engine.

Given a gameplay layout it adds, without touching any hitbox:

* structure art  - colored fill over solid blocks, merged outlines along exposed edges,
                   inner-corner patches, and glow gradients around the outside
* background     - a parallax-style skyline / pillars / floating shapes on B3-B4
* particles      - small dots and squares near the action (marked High Detail)
* colors         - every section gets its own palette via color triggers
* music sync     - optional pulse triggers on every beat when you give a BPM

All generated objects go on their own editor layer so they are easy to inspect or delete.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

from . import objects as O
from .analyze import Cell, Layout, Section, analyze, num, scale_of
from .level import ColorChannel, Level, fmt_number
from .themes import RGB, Theme, mix

DECO_ROLES = ("fill", "outline", "glow", "hazard", "bg_far", "bg_near", "bg_outline", "bg_detail", "particle")
BUILTIN_CHANNELS = {"bg": O.BG, "ground": O.G1, "ground2": O.G2, "line": O.LINE}
BLENDING_ROLES = {"glow", "particle", "line"}
RECOLORABLE_HAZARDS = {8, 39, 103, 392}

UP, DOWN, LEFT, RIGHT = (0, 1), (0, -1), (-1, 0), (1, 0)


@dataclass
class Options:
    seed: int = 1
    bpm: float | None = None
    first_beat: float = 0.0        # seconds after the level starts
    structures: bool = True
    background: bool = True
    particles: bool = True
    color_changes: bool = True
    recolor_gameplay: bool = True
    max_piece_scale: int = 8       # longest merged piece, in blocks (huge objects can pop in late)


@dataclass
class Report:
    added: Counter = field(default_factory=Counter)
    channels: dict[str, int] = field(default_factory=dict)
    editor_layer: int = 0
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    original_objects: int = 0
    total_objects: int = 0

    def summary(self) -> str:
        lines = [
            f"Objects: {self.original_objects} -> {self.total_objects} (+{sum(self.added.values())})",
            "Added: " + ", ".join(f"{k} {v}" for k, v in sorted(self.added.items())),
            f"Decoration is on editor layer {self.editor_layer}.",
            "Color channels: " + ", ".join(f"{k}={v}" for k, v in self.channels.items()),
            f"Sections ({len(self.sections)}):",
        ]
        for s in self.sections:
            lines.append(f"  #{s.index}: blocks {int(s.x_start // 30)}-{int(s.x_end // 30)} {s.mode:<6} intensity {s.intensity:.2f}")
        lines += [f"WARNING: {w}" for w in self.warnings]
        return "\n".join(lines)


def decorate(level: Level, theme: Theme, options: Options | None = None) -> tuple[Level, Report]:
    return Decorator(level, theme, options or Options()).run()


class Decorator:
    def __init__(self, level: Level, theme: Theme, options: Options):
        self.src = level
        self.level = level.copy()
        self.theme = theme
        self.opt = options
        self.rng = random.Random(options.seed)
        self.lay: Layout = analyze(level)
        self.report = Report(original_objects=len(level.objects), sections=self.lay.sections)
        self.new_objects: list[dict[str, str]] = []
        self.channels = self._allocate_channels()
        self.editor_layer = self._free_editor_layer()
        self.report.channels = dict(self.channels)
        self.report.editor_layer = self.editor_layer

    # ------------------------------------------------------------------ setup
    def _allocate_channels(self) -> dict[str, int]:
        used = set(self.src.colors())
        for obj in self.src.objects:
            for key in (O.MAIN_COLOR, O.DETAIL_COLOR, "23", "50"):
                if obj.get(key, "").isdigit():
                    used.add(int(obj[key]))
            if obj.get(O.ID) == str(O.PULSE_TRIGGER) and obj.get("52", "0") != "1" and obj.get("51", "").isdigit():
                used.add(int(obj["51"]))
        free = [c for c in range(1, 1000) if c not in used]
        if len(free) < len(DECO_ROLES):
            raise ValueError(f"the level already uses {len(used)} color channels; "
                             f"decorating needs {len(DECO_ROLES)} free ones between 1 and 999")
        channels = dict(zip(DECO_ROLES, free))
        channels.update(BUILTIN_CHANNELS)
        return channels

    def _free_editor_layer(self) -> int:
        layers = [int(o[O.EDITOR_LAYER]) for o in self.src.objects if o.get(O.EDITOR_LAYER, "").isdigit()]
        return max(layers, default=0) + 1

    # --------------------------------------------------------------- building
    def add(self, kind: str, oid: int, x: float, y: float, z: int, role: str, *, rot: float = 0,
            sx: float = 1, sy: float = 1, flip_x: bool = False, flip_y: bool = False,
            high_detail: bool = False, no_glow: bool = False) -> None:
        obj = {O.ID: str(oid), O.X: fmt_number(round(x, 3)), O.Y: fmt_number(round(y, 3))}
        if flip_x:
            obj[O.FLIP_X] = "1"
        if flip_y:
            obj[O.FLIP_Y] = "1"
        if rot % 360:
            obj[O.ROTATION] = fmt_number(round(rot % 360, 3))
        obj[O.EDITOR_LAYER] = str(self.editor_layer)
        obj[O.MAIN_COLOR] = str(self.channels[role])
        obj[O.Z_LAYER] = str(z)
        if no_glow:
            obj[O.NO_GLOW] = "1"
        if high_detail:
            obj[O.HIGH_DETAIL] = "1"
        if sx != 1:
            obj[O.SCALE_X] = fmt_number(round(sx, 3))
        if sy != 1:
            obj[O.SCALE_Y] = fmt_number(round(sy, 3))
        self.new_objects.append(obj)
        self.report.added[kind] += 1

    def _chunks(self, start: int, length: int):
        """Split a run into pieces no longer than max_piece_scale, as evenly as possible."""
        pieces = math.ceil(length / self.opt.max_piece_scale)
        base, extra = divmod(length, pieces)
        pos = start
        for p in range(pieces):
            n = base + (1 if p < extra else 0)
            yield pos, n
            pos += n

    @staticmethod
    def _runs(cells: set[Cell], horizontal: bool):
        """Group cells into maximal straight runs. Yields (fixed, start, length)."""
        by_line: dict[int, list[int]] = {}
        for i, j in cells:
            fixed, var = (j, i) if horizontal else (i, j)
            by_line.setdefault(fixed, []).append(var)
        for fixed, values in sorted(by_line.items()):
            values.sort()
            start = prev = values[0]
            for v in values[1:] + [None]:
                if v is not None and v == prev + 1:
                    prev = v
                    continue
                yield fixed, start, prev - start + 1
                if v is not None:
                    start = prev = v

    # ---------------------------------------------------------- structures
    def _exposed(self, cell: Cell, d: tuple[int, int]) -> bool:
        n = (cell[0] + d[0], cell[1] + d[1])
        return n not in self.lay.solid and n[1] >= 0  # the ground counts as solid

    def structures(self) -> None:
        solid = self.lay.solid
        U = O.UNIT
        # Fill: hides the default block art under a flat, theme-colored surface.
        for j, i0, n in self._runs(solid, horizontal=True):
            for i, m in self._chunks(i0, n):
                self.add("fill", O.FILL_SQUARE, U * i + 15 * m, U * j + 15, O.T2, "fill", sx=m)

        edge_specs = {
            # direction: (outline offset, outline rotation, glow offset, glow rotation)
            UP: ((0, 14.25), 0, (0, 25), 0),
            DOWN: ((0, -14.25), 180, (0, -25), 180),
            LEFT: ((-14.25, 0), 270, (-25, 0), 270),
            RIGHT: ((14.25, 0), 90, (25, 0), 90),
        }
        for d, (line_off, line_rot, glow_off, glow_rot) in edge_specs.items():
            exposed = {c for c in solid if self._exposed(c, d)}
            horizontal = d in (UP, DOWN)
            for fixed, start, n in self._runs(exposed, horizontal):
                for s, m in self._chunks(start, n):
                    center_var = U * s + 15 * m
                    cx, cy = (center_var, U * fixed + 15) if horizontal else (U * fixed + 15, center_var)
                    self.add("outline", O.OUTLINE_LINE, cx + line_off[0], cy + line_off[1], O.T3, "outline",
                             rot=line_rot, sx=m)
                    self.add("glow", O.GLOW_EDGE, cx + glow_off[0], cy + glow_off[1], O.B2, "glow",
                             rot=glow_rot, sx=m)

        for (i, j) in solid:
            cx, cy = U * i + 15, U * j + 15
            # Inner corners: both neighbours solid, diagonal empty -> patch the 1.5u gap in the outline.
            for (dx, dy), rot in (((-1, 1), 0), ((1, 1), 90), ((1, -1), 180), ((-1, -1), 270)):
                if (i + dx, j) in solid and (i, j + dy) in solid and (i + dx, j + dy) not in solid:
                    self.add("outline", O.OUTLINE_CORNER_DOT, cx, cy, O.T3, "outline", rot=rot)
            # Outer corners: round the glow off with a quarter-radial gradient in the diagonal cell.
            for dx, dy in ((-1, 1), (1, 1), (-1, -1), (1, -1)):
                if j + dy < 0:
                    continue
                if all(c not in solid for c in ((i + dx, j), (i, j + dy), (i + dx, j + dy))):
                    self.add("glow", O.GLOW_CORNER, cx + 25 * dx, cy + 25 * dy, O.B2, "glow",
                             flip_x=dx > 0, flip_y=dy < 0)

        # Off-grid blocks: an exact overlay (same position, rotation, scale) instead of the merged grid art.
        for idx in self.lay.loose_objects:
            obj = self.src.objects[idx]
            if int(obj[O.ID]) not in O.SOLID_BLOCKS:
                continue  # slopes are only recolored
            x, y, rot = num(obj, O.X), num(obj, O.Y), num(obj, O.ROTATION)
            sx, sy = scale_of(obj)
            self.add("fill", O.FILL_SQUARE, x, y, O.T2, "fill", rot=rot, sx=sx, sy=sy)
            self.add("outline", O.OUTLINE_SQUARE, x, y, O.T3, "outline", rot=rot, sx=sx, sy=sy, no_glow=True)

        # Slabs: glow on top so platforms read the same way blocks do.
        for j, i0, n in self._runs(self.lay.slabs, horizontal=True):
            for i, m in self._chunks(i0, n):
                self.add("glow", O.GLOW_EDGE, U * i + 15 * m, U * (j + 1) + 10, O.B2, "glow", sx=m)

    # ---------------------------------------------------------- background
    def background(self) -> None:
        style = self.theme.bg_style
        x0, x1 = -10 * O.UNIT, self.lay.max_x + 20 * O.UNIT
        top = max(self.lay.max_y + 4 * O.UNIT, 12 * O.UNIT)
        if style == "city":
            self._skyline(x0, x1, O.B4, "bg_far", "bg_near", widths=(2, 5), gaps=(0, 2), heights=(4, 11), windows=False)
            self._skyline(x0, x1, O.B3, "bg_near", "bg_outline", widths=(3, 7), gaps=(1, 4), heights=(2, 7), windows=True)
        elif style == "pillars":
            self._pillars(x0, x1, top)
        elif style == "geometric":
            self._floating_shapes(x0, x1, top)

    def _rect(self, kind: str, i0: int, j0: int, w: int, h: int, z: int, fill_role: str, line_role: str | None,
              sides=(UP, LEFT, RIGHT)) -> None:
        """A w x h block rectangle (cell coords) with optional outlines, split into bounded pieces."""
        U = O.UNIT
        for i, m in self._chunks(i0, w):
            for j, k in self._chunks(j0, h):
                self.add(kind, O.FILL_SQUARE, U * i + 15 * m, U * j + 15 * k, z, fill_role, sx=m, sy=k)
        if not line_role:
            return
        for side in sides:
            if side in (UP, DOWN):
                y = U * (j0 + h) - 0.75 if side == UP else U * j0 + 0.75
                for i, m in self._chunks(i0, w):
                    self.add(kind, O.OUTLINE_LINE, U * i + 15 * m, y, z, line_role, rot=0 if side == UP else 180, sx=m)
            else:
                x = U * i0 + 0.75 if side == LEFT else U * (i0 + w) - 0.75
                for j, k in self._chunks(j0, h):
                    self.add(kind, O.OUTLINE_LINE, x, U * j + 15 * k, z, line_role, rot=270 if side == LEFT else 90, sx=k)

    def _skyline(self, x0, x1, z, fill_role, line_role, widths, gaps, heights, windows) -> None:
        i = math.floor(x0 / O.UNIT)
        while i * O.UNIT < x1:
            w = self.rng.randint(*widths)
            h = self.rng.randint(*heights)
            self._rect("background", i, 0, w, h, z, fill_role, line_role)
            if windows and w >= 3 and h >= 3:
                for wi in range(w):
                    for wj in range(1, h - 1):
                        if self.rng.random() < 0.28:
                            self.add("background", O.PARTICLE_SQUARE, O.UNIT * (i + wi) + 15, O.UNIT * wj + 15,
                                     z, "bg_detail", high_detail=True)
            i += w + self.rng.randint(*gaps)

    def _pillars(self, x0, x1, top) -> None:
        top_row = math.ceil(top / O.UNIT)
        i = math.floor(x0 / O.UNIT)
        while i * O.UNIT < x1:
            w = self.rng.choice((1, 1, 2))
            h = self.rng.randint(3, 9)
            self._rect("background", i, 0, w, h, O.B3, "bg_near", "bg_outline")
            self.add("background", O.GLOW_SQUARE, O.UNIT * i + 15 * w, O.UNIT * h + 15, O.B3, "bg_outline", sx=w)
            if self.rng.random() < 0.6:
                hh = self.rng.randint(2, 6)
                self._rect("background", i + self.rng.randint(1, 3), top_row - hh, w, hh, O.B3, "bg_near", "bg_outline",
                           sides=(DOWN, LEFT, RIGHT))
            i += w + self.rng.randint(4, 9)
        # Faint big squares far behind for depth.
        i = math.floor(x0 / O.UNIT)
        while i * O.UNIT < x1:
            size = self.rng.randint(3, 6)
            self._rect("background", i, self.rng.randint(0, max(1, top_row - size)), size, size, O.B4, "bg_far", None)
            i += size + self.rng.randint(3, 8)

    def _floating_shapes(self, x0, x1, top) -> None:
        step = 5 * O.UNIT
        x = x0
        while x < x1:
            for _ in range(self.rng.choice((1, 1, 2))):
                s = self.rng.uniform(1.2, 3.4)
                y = self.rng.uniform(30 * s, max(30 * s + 1, top))  # keep the whole shape above the floor
                rot = 45 + self.rng.choice((0, 0, 15, -15))
                far = self.rng.random() < 0.6
                z, fill, line = (O.B4, "bg_far", "bg_near") if far else (O.B3, "bg_near", "bg_outline")
                jx = x + self.rng.uniform(0, step)
                self.add("background", O.FILL_SQUARE, jx, y, z, fill, rot=rot, sx=s, sy=s)
                self.add("background", O.OUTLINE_SQUARE, jx, y, z, line, rot=rot, sx=s, sy=s, no_glow=True)
            x += step

    # ----------------------------------------------------------- particles
    def particles(self) -> None:
        lay = self.lay
        density = self.theme.particle_density
        if density <= 0:
            return
        near: set[Cell] = set()
        for (i, j) in lay.solid | lay.slabs:
            for di in range(-3, 4):
                for dj in range(-3, 4):
                    near.add((i + di, j + dj))
        i_max = math.ceil((lay.max_x + 10 * O.UNIT) / O.UNIT)
        j_max = math.ceil((lay.max_y + 3 * O.UNIT) / O.UNIT)
        for i in range(-5, i_max):
            section = lay.section_at(i * O.UNIT)
            for j in range(0, j_max + 1):
                cell = (i, j)
                if not lay.is_free(cell):
                    continue
                p = (0.16 if cell in near else 0.035) * density * (0.5 + section.intensity)
                if self.rng.random() >= p:
                    continue
                oid = O.PARTICLE_SHAPES[self.rng.choice(self.theme.particle_shapes)]
                s = round(self.rng.uniform(0.45, 1.25), 2)
                self.add("particles", oid, O.UNIT * i + self.rng.uniform(5, 25), O.UNIT * j + self.rng.uniform(5, 25),
                         O.B1, "particle", rot=self.rng.choice((0, 45)) if oid == O.PARTICLE_SQUARE else 0,
                         sx=s, sy=s, high_detail=True)

    # -------------------------------------------------------------- colors
    def _role_colors(self, section_index: int) -> dict[str, RGB]:
        return self.theme.palette_for(section_index).roles()

    def _opacity(self, role: str) -> float:
        return {"glow": self.theme.glow_opacity, "particle": 0.85}.get(role, 1.0)

    def initial_colors(self) -> None:
        colors = self.level.colors()
        for role, rgb in self._role_colors(0).items():
            ch = self.channels[role]
            colors[ch] = ColorChannel(ch, *rgb, opacity=self._opacity(role), blending=role in BLENDING_ROLES)
        self.level.set_colors(colors)

    def _trigger_y(self, slot: int) -> float:
        return O.UNIT * (math.ceil(self.lay.max_y / O.UNIT) + 8 + slot) + 15

    def color_changes(self) -> None:
        for section in self.lay.sections[1:]:
            if self.theme.palette_for(section.index) == self.theme.palette_for(section.index - 1):
                continue
            duration = 0.35 if section.intensity > 0.66 else 0.8
            for slot, (role, rgb) in enumerate(self._role_colors(section.index).items()):
                trig = {
                    O.ID: str(O.COLOR_TRIGGER), O.X: fmt_number(round(section.x_start, 2)), O.Y: fmt_number(self._trigger_y(slot)),
                    "7": str(rgb[0]), "8": str(rgb[1]), "9": str(rgb[2]), "10": fmt_number(duration),
                    "23": str(self.channels[role]), "35": fmt_number(self._opacity(role)), "36": "1",
                    O.EDITOR_LAYER: str(self.editor_layer),
                }
                if role in BLENDING_ROLES:
                    trig["17"] = "1"
                self.new_objects.append(trig)
                self.report.added["color triggers"] += 1

    def beat_pulses(self) -> None:
        bpm = self.opt.bpm
        if not bpm or bpm <= 0:
            return
        period = 60.0 / bpm
        end_x = self.lay.max_x + 10 * O.UNIT
        k = 0
        while True:
            t = self.opt.first_beat + k * period
            x = self.lay.x_at_time(t)
            if x > end_x:
                break
            section = self.lay.section_at(x)
            downbeat = k % 4 == 0
            targets: list[tuple[str, RGB]] = []
            palette = self.theme.palette_for(section.index)
            flash = mix(palette.primary, (255, 255, 255), 0.6)
            if section.intensity >= 0.33 or k % 2 == 0:
                targets.append(("glow", flash))
            if section.intensity >= 0.66:
                targets.append(("outline", flash))
                if downbeat:
                    targets.append(("bg", mix(palette.bg, palette.primary, 0.3)))
            for slot, (role, rgb) in enumerate(targets):
                self.new_objects.append({
                    O.ID: str(O.PULSE_TRIGGER), O.X: fmt_number(round(x, 2)), O.Y: fmt_number(self._trigger_y(20 + slot)),
                    "7": str(rgb[0]), "8": str(rgb[1]), "9": str(rgb[2]),
                    "45": "0", "46": "0.05", "47": fmt_number(round(min(0.45, period * 0.8), 3)),
                    "51": str(self.channels[role]), "36": "1", O.EDITOR_LAYER: str(self.editor_layer),
                })
                self.report.added["pulse triggers"] += 1
            k += 1

    # ------------------------------------------------------------ gameplay
    def tune_gameplay_objects(self) -> None:
        """Only visual properties change: glow halo off under our fill, theme colors on spikes, slabs,
        slopes and off-grid blocks (those can't be covered by the grid-aligned fill)."""
        objs = self.level.objects
        def default_color(obj):  # the editor often writes 21=1004 (the default) explicitly
            return obj.get(O.MAIN_COLOR, str(O.OBJ)) == str(O.OBJ)

        if self.opt.structures:
            for idx in self.lay.solid_objects + self.lay.loose_objects:
                objs[idx][O.NO_GLOW] = "1"
        if self.opt.recolor_gameplay:
            for idx in self.lay.hazard_objects:
                obj = objs[idx]
                if int(obj[O.ID]) in RECOLORABLE_HAZARDS and default_color(obj):
                    obj[O.MAIN_COLOR] = str(self.channels["hazard"])
            for idx in self.lay.slab_objects + self.lay.loose_objects:
                if default_color(objs[idx]):
                    objs[idx][O.MAIN_COLOR] = str(self.channels["outline"])

    # ----------------------------------------------------------------- run
    def run(self) -> tuple[Level, Report]:
        if not self.lay.solid:
            self.report.warnings.append("no standard solid blocks found - only background, particles and colors were added")
        if self.lay.deco_object_count > 0.5 * max(1, len(self.src.objects)):
            self.report.warnings.append("this level already has a lot of decoration; the result may look busy")
        if self.opt.structures:
            self.structures()
        if self.opt.background:
            self.background()
        if self.opt.particles:
            self.particles()
        self.tune_gameplay_objects()
        self.initial_colors()
        if self.opt.color_changes:
            self.color_changes()
        self.beat_pulses()
        self.level.objects.extend(self.new_objects)
        self.report.total_objects = len(self.level.objects)
        if self.report.total_objects > 80_000:
            self.report.warnings.append("over 80k objects - consider --no-particles or a sparser background")
        return self.level, self.report
