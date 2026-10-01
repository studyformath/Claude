"""Render a quick PNG preview of a level using simple shapes (no game assets needed).

It is an approximation of what the game draws: it knows the gameplay objects and
every decoration piece the decorator places, honours colors, color triggers,
z layers, rotation, flips, scale and additive blending, and skips anything else.
"""

from __future__ import annotations

import bisect
import math

import numpy as np
from PIL import Image, ImageDraw

from . import objects as O
from .analyze import analyze, num, scale_of
from .level import Level

SS = 4  # supersampling for thin lines

DEFAULT_CHANNEL_RGB = {O.BG: (40, 125, 255), O.G1: (0, 102, 255), O.G2: (0, 70, 200), O.LINE: (255, 255, 255),
                       O.OBJ: (255, 255, 255), 1010: (0, 0, 0), 1011: (255, 255, 255)}

ORB_COLORS = {36: (255, 230, 0), 84: (40, 200, 255), 141: (255, 80, 220), 1022: (60, 255, 90), 1330: (30, 30, 30),
              1333: (255, 60, 60), 1594: (240, 240, 240), 1704: (60, 255, 90), 1751: (255, 80, 220), 3004: (180, 80, 255),
              3027: (80, 255, 255)}
PAD_COLORS = {35: (255, 230, 0), 67: (40, 200, 255), 140: (255, 80, 220), 1332: (255, 60, 60), 3005: (180, 80, 255)}
PORTAL_COLORS = {12: (60, 255, 90), 13: (255, 80, 220), 47: (255, 70, 40), 111: (255, 160, 40), 660: (40, 200, 255),
                 745: (240, 240, 240), 1331: (180, 80, 255), 1933: (255, 230, 0), 10: (40, 200, 255), 11: (255, 230, 0),
                 99: (60, 255, 90), 101: (255, 80, 220)}
DEFAULT_Z = {O.FILL_SQUARE: O.B2, O.GLOW_EDGE: O.B2, O.GLOW_CORNER: O.B2, O.GLOW_SQUARE: O.B2,
             **{oid: O.B1 for oid in O.PARTICLE_SHAPES.values()},
             O.OUTLINE_SQUARE: O.T1, O.OUTLINE_LINE: O.T1, O.OUTLINE_CORNER_DOT: O.T1}


# ----------------------------------------------------------------------------- colors
class ColorTimeline:
    """Channel colors along the level: initial colors plus color triggers (applied instantly)."""

    def __init__(self, level: Level):
        self.initial = {ch: (c.r, c.g, c.b, c.opacity, c.blending) for ch, c in level.colors().items()}
        self.changes: dict[int, tuple[list[float], list[tuple]]] = {}
        trig = [o for o in level.objects if o.get(O.ID) == str(O.COLOR_TRIGGER) and "23" in o]
        for o in sorted(trig, key=lambda o: float(o[O.X])):
            x = float(o[O.X])
            ch = int(o["23"])
            xs, vals = self.changes.setdefault(ch, ([], []))
            xs.append(x)
            vals.append((int(o.get("7", 255)), int(o.get("8", 255)), int(o.get("9", 255)),
                         float(o.get("35", 1)), o.get("17") == "1"))

    def at(self, channel: int, x: float) -> tuple[tuple[int, int, int], float, bool]:
        if channel in self.changes:
            xs, vals = self.changes[channel]
            k = bisect.bisect_right(xs, x) - 1
            if k >= 0:
                r, g, b, a, blend = vals[k]
                return (r, g, b), a, blend
        if channel in self.initial:
            r, g, b, a, blend = self.initial[channel]
            return (r, g, b), a, blend
        return DEFAULT_CHANNEL_RGB.get(channel, (255, 255, 255)), 1.0, False


# ----------------------------------------------------------------------------- shapes
def _layers(oid: int, obj: dict[str, str]):
    """(w, h, mask kind, color) layers for an object in draw order; empty for objects we don't draw."""
    main = int(obj[O.MAIN_COLOR]) if obj.get(O.MAIN_COLOR, "").isdigit() else None
    if oid in O.SOLID_BLOCKS:
        return [(30, 30, "rect", ("rgb", (14, 14, 18))), (30, 30, "frame", ("ch", main or O.OBJ))]
    if oid in O.SLABS:
        return [(30, 13.5, "rect", ("rgb", (14, 14, 18))), (30, 13.5, "frame", ("ch", main or O.OBJ))]
    if oid in (8, 39, 103, 392):
        w, h = {8: (30, 30), 39: (30, 13.5), 103: (20, 19), 392: (12.5, 12)}[oid]
        return [(w, h, "tri", ("rgb", (10, 10, 12))), (w, h, "tri_frame", ("ch", main or O.OBJ))]
    if oid in O.HAZARDS:
        return [(30, 26, "tri", ("rgb", (10, 10, 12)))]
    if oid in ORB_COLORS:
        return [(30, 30, "ring", ("rgb", ORB_COLORS[oid])), (16, 16, "disc", ("rgb", ORB_COLORS[oid]))]
    if oid in PAD_COLORS:
        return [(25, 5, "rect", ("rgb", PAD_COLORS[oid]))]
    if oid in PORTAL_COLORS:
        return [(26, 86, "ellipse_frame", ("rgb", PORTAL_COLORS[oid]))]
    if oid in O.SPEED_PORTALS:
        return [(34, 50, "chevron", ("rgb", (255, 210, 60)))]
    color = ("ch", main or 1004)
    return {
        O.FILL_SQUARE: [(30, 30, "rect", color)],
        O.OUTLINE_LINE: [(30, 30, "hline", color)],
        O.OUTLINE_CORNER_DOT: [(30, 30, "corner_dot", color)],
        O.OUTLINE_SQUARE: [(30, 30, "frame", color)],
        O.GLOW_EDGE: [(30, 20, "vgrad", color)],
        O.GLOW_SQUARE: [(30, 30, "vgrad", color)],
        O.GLOW_CORNER: [(20, 20, "corner_grad", color)],
        O.PARTICLE_DOT: [(8, 8, "disc", color)],
        O.PARTICLE_CROSS: [(6, 6, "cross", color)],
        O.PARTICLE_TRIANGLE: [(6, 6, "tri", color)],
        O.PARTICLE_SQUARE: [(7.5, 7.5, "rect", color)],
    }.get(oid, [])


def _mask(kind: str, w: float, h: float, k: float) -> Image.Image:
    W, H = max(1, round(w * k)), max(1, round(h * k))
    if kind in ("vgrad", "corner_grad"):
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        if kind == "vgrad":  # bright at the bottom edge, fading upward
            a = (yy + 0.5) / H
            a = a ** 1.6
        elif kind == "corner_grad":  # bright at the bottom-right corner
            r = np.hypot(W - xx - 0.5, H - yy - 0.5) / max(W, H)
            a = np.clip(1 - r, 0, 1) ** 1.6
        return Image.fromarray((a * 255).astype(np.uint8), "L")
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    t = max(1, round(1.5 * k))  # outline thickness
    if kind == "rect":
        d.rectangle([0, 0, W - 1, H - 1], fill=255)
    elif kind == "frame":
        d.rectangle([0, 0, W - 1, H - 1], outline=255, width=t)
    elif kind == "hline":  # 1.5u line through the center
        d.rectangle([0, H / 2 - t / 2, W - 1, H / 2 + t / 2 - 1], fill=255)
    elif kind == "corner_dot":  # top-left corner
        d.rectangle([0, 0, t - 1, t - 1], fill=255)
    elif kind == "tri":
        d.polygon([(0, H - 1), (W - 1, H - 1), (W / 2, 0)], fill=255)
    elif kind == "tri_frame":
        d.line([(0, H - 1), (W / 2, 0), (W - 1, H - 1), (0, H - 1)], fill=255, width=t)
    elif kind == "ring":
        d.ellipse([0, 0, W - 1, H - 1], outline=255, width=max(1, round(3 * k)))
    elif kind == "cross":
        d.line([(0, 0), (W - 1, H - 1)], fill=255, width=max(1, round(1.5 * k)))
        d.line([(0, H - 1), (W - 1, 0)], fill=255, width=max(1, round(1.5 * k)))
    elif kind == "disc":
        d.ellipse([0, 0, W - 1, H - 1], fill=255)
    elif kind == "ellipse_frame":
        d.ellipse([0, 0, W - 1, H - 1], outline=255, width=max(1, round(4 * k)))
    elif kind == "chevron":
        d.polygon([(0, 0), (W / 2, 0), (W - 1, H / 2), (W / 2, H - 1), (0, H - 1), (W / 2, H / 2)], fill=255)
    return img


# ----------------------------------------------------------------------------- render
def render(level: Level, path: str, *, blocks: tuple[int, int] | None = None, strip_blocks: int = 70,
           px_per_unit: float = 0.6, max_strips: int = 8) -> None:
    """Render ``level`` to ``path`` as stacked horizontal strips (one strip = ``strip_blocks`` blocks)."""
    lay = analyze(level)
    colors = ColorTimeline(level)
    if blocks:
        x_start, x_end = blocks[0] * O.UNIT, blocks[1] * O.UNIT
    else:
        x_start, x_end = -6 * O.UNIT, lay.max_x + 8 * O.UNIT
    strip_w = strip_blocks * O.UNIT
    n_strips = min(max_strips, max(1, math.ceil((x_end - x_start) / strip_w)))
    y_bottom = -2.5 * O.UNIT
    y_top = max(lay.max_y + 5 * O.UNIT, 12 * O.UNIT)
    k = px_per_unit
    W, H = round(strip_w * k), round((y_top - y_bottom) * k)

    # Pre-sort drawable objects by (z layer, z order, index).
    drawable = []
    for idx, obj in enumerate(level.objects):
        try:
            oid = int(obj[O.ID])
        except (KeyError, ValueError):
            continue
        layers = _layers(oid, obj)
        if not layers:
            continue
        z = int(num(obj, O.Z_LAYER, 0)) or DEFAULT_Z.get(oid, O.T1)
        drawable.append((z, int(num(obj, O.Z_ORDER, 0)), idx, oid, obj, layers))
    drawable.sort(key=lambda t: (t[0], t[1], t[2]))

    strips = []
    for s in range(n_strips):
        sx0 = x_start + s * strip_w
        canvas = np.zeros((H, W, 3), np.float32)
        # Background and ground colors follow the color triggers column by column.
        for px in range(0, W, max(1, round(15 * k))):
            x = sx0 + px / k
            bg, _, _ = colors.at(O.BG, x)
            g1, _, _ = colors.at(O.G1, x)
            gy = round((y_top - 0) * k)
            canvas[:gy, px:px + round(15 * k) + 1] = bg
            canvas[gy:, px:px + round(15 * k) + 1] = g1
        for z, _zo, _idx, oid, obj, layers in drawable:
            x, y = num(obj, O.X), num(obj, O.Y)
            if x < sx0 - 300 or x > sx0 + strip_w + 300:
                continue
            _draw(canvas, obj, x, y, layers, colors, sx0, y_top, k)
        # Ground line on top of everything below it.
        gy = round(y_top * k)
        for px in range(0, W, max(1, round(15 * k))):
            line, _, _ = colors.at(O.LINE, sx0 + px / k)
            canvas[gy - 1:gy + 1, px:px + round(15 * k) + 1] = line
        img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB")
        ImageDraw.Draw(img).text((6, 4), f"blocks {int(sx0 // 30)}-{int((sx0 + strip_w) // 30)}", fill=(255, 255, 255))
        strips.append(img)

    gap = 6
    out = Image.new("RGB", (W, n_strips * H + (n_strips - 1) * gap), (20, 20, 24))
    for s, img in enumerate(strips):
        out.paste(img, (0, s * (H + gap)))
    out.save(path)


def _draw(canvas, obj, x, y, layers, colors: ColorTimeline, sx0, y_top, k) -> None:
    scx, scy = scale_of(obj)
    rot = num(obj, O.ROTATION)
    flip_x = (obj.get(O.FLIP_X) == "1") != (scx < 0)
    flip_y = (obj.get(O.FLIP_Y) == "1") != (scy < 0)
    for w, h, kind, (ctype, cval) in layers:
        if ctype == "ch":
            rgb, alpha, blend = colors.at(cval, x)
        else:
            rgb, alpha, blend = cval, 1.0, False
        if alpha <= 0:
            continue
        mask = _mask(kind, w * abs(scx), h * abs(scy), k * SS)
        if flip_x:
            mask = mask.transpose(Image.FLIP_LEFT_RIGHT)
        if flip_y:
            mask = mask.transpose(Image.FLIP_TOP_BOTTOM)
        if rot % 360:
            mask = mask.rotate(-rot, resample=Image.BILINEAR, expand=True)  # GD rotation is clockwise
        mw, mh = max(1, round(mask.width / SS)), max(1, round(mask.height / SS))
        mask = mask.resize((mw, mh), Image.BOX)
        a = np.asarray(mask, np.float32)[..., None] / 255.0 * alpha
        cx, cy = (x - sx0) * k, (y_top - y) * k
        x0, y0 = round(cx - mw / 2), round(cy - mh / 2)
        X0, Y0 = max(0, x0), max(0, y0)
        X1, Y1 = min(canvas.shape[1], x0 + mw), min(canvas.shape[0], y0 + mh)
        if X0 >= X1 or Y0 >= Y1:
            continue
        a = a[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]
        region = canvas[Y0:Y1, X0:X1]
        col = np.array(rgb, np.float32)
        if blend:
            region += col * a
        else:
            region *= (1 - a)
            region += col * a
