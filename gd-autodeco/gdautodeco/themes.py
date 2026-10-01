"""Color themes. A theme is a few palettes (one per section, cycled) plus style knobs."""

from __future__ import annotations

from dataclasses import dataclass, field

RGB = tuple[int, int, int]

BG_STYLES = ("city", "pillars", "geometric", "none")
PARTICLE_SHAPE_NAMES = ("dot", "square", "cross", "triangle")


def hex_to_rgb(value: str) -> RGB:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"expected #RRGGBB, got {value!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


@dataclass
class Palette:
    bg: RGB          # sky / background
    fill: RGB        # inside of gameplay structures (keep it dark so gameplay reads clearly)
    primary: RGB     # outlines + glow
    secondary: RGB   # particles + background details
    ground: RGB | None = None

    @classmethod
    def from_hex(cls, bg: str, fill: str, primary: str, secondary: str, ground: str | None = None) -> "Palette":
        return cls(hex_to_rgb(bg), hex_to_rgb(fill), hex_to_rgb(primary), hex_to_rgb(secondary),
                   hex_to_rgb(ground) if ground else None)

    def roles(self) -> dict[str, RGB]:
        """Expand the five theme colors into every color channel the decorator uses."""
        white = (255, 255, 255)
        ground = self.ground or mix(self.fill, self.bg, 0.35)
        return {
            "bg": self.bg,
            "ground": ground,
            "ground2": mix(ground, (0, 0, 0), 0.35),
            "line": self.primary,
            "fill": self.fill,
            "outline": self.primary,
            "glow": self.primary,
            "hazard": mix(self.primary, white, 0.45),
            "bg_far": mix(self.bg, self.primary, 0.07),
            "bg_near": mix(self.bg, self.primary, 0.15),
            "bg_outline": mix(self.bg, self.primary, 0.38),
            "bg_detail": mix(self.bg, self.secondary, 0.4),
            "particle": self.secondary,
        }


@dataclass
class Theme:
    name: str
    palettes: list[Palette]
    bg_style: str = "city"
    particle_density: float = 0.5   # 0..1
    glow_opacity: float = 0.8       # 0..1
    particle_shapes: tuple[str, ...] = ("dot", "dot", "square")
    description: str = ""
    section_moods: list[str] = field(default_factory=list)

    def palette_for(self, section_index: int) -> Palette:
        return self.palettes[section_index % len(self.palettes)]


def _t(name, desc, style, density, glow, shapes, *palettes) -> Theme:
    return Theme(name, [Palette.from_hex(*p) for p in palettes], style, density, glow, shapes, desc)


THEMES: dict[str, Theme] = {t.name: t for t in [
    _t("neon", "Dark navy with electric cyan and magenta - classic glow deco.", "city", 0.55, 0.85, ("dot", "dot", "square"),
       ("#070a1f", "#0b1030", "#22e4ff", "#ff3df2"),
       ("#12051f", "#1a0830", "#ff3df2", "#22e4ff"),
       ("#04140f", "#062018", "#3dff9e", "#d8ff3d")),
    _t("sunset", "Warm purple-to-orange evening skyline.", "city", 0.45, 0.75, ("dot", "dot", "square"),
       ("#2a0f3d", "#1c0a29", "#ff8a3d", "#ffd23d", "#3b1450"),
       ("#3d0f2a", "#290a1c", "#ff4f6d", "#ffb13d", "#501432"),
       ("#14123d", "#0d0b29", "#ffb13d", "#ff6ad5", "#1d1a50")),
    _t("inferno", "Black and red with fiery orange highlights.", "pillars", 0.65, 0.9, ("dot", "triangle", "triangle"),
       ("#120303", "#1a0505", "#ff4a1c", "#ffc21c", "#260707"),
       ("#1a0703", "#240a05", "#ffa21c", "#ff3a1c", "#2e0c07")),
    _t("frost", "Deep blue ice cave with white sparkle.", "geometric", 0.6, 0.7, ("dot", "cross", "square"),
       ("#04122b", "#061a3d", "#8fe9ff", "#ffffff", "#0a2550"),
       ("#0a0f2e", "#0f1640", "#b39dff", "#e6f7ff", "#141c55")),
    _t("toxic", "Murky green lab with acid highlights.", "pillars", 0.5, 0.8, ("dot", "square"),
       ("#061208", "#0a1f0d", "#8cff1a", "#f2ff4d", "#0e2a12"),
       ("#0f1206", "#1a1f0a", "#f2ff4d", "#1affb2", "#262a0e")),
    _t("vapor", "Retro vaporwave pink and teal.", "geometric", 0.45, 0.75, ("triangle", "cross", "dot"),
       ("#1f0b3a", "#160829", "#ff71ce", "#01cdfe", "#2d1052"),
       ("#0b263a", "#081a29", "#05ffa1", "#b967ff", "#103552")),
    _t("mono", "Black and white, minimal and clean.", "geometric", 0.35, 0.6, ("square", "dot"),
       ("#0a0a0a", "#141414", "#ffffff", "#9a9a9a", "#1c1c1c"),
       ("#141414", "#000000", "#d0d0d0", "#ffffff", "#222222")),
]}


def theme_from_dict(data: dict) -> Theme:
    """Build a theme from JSON (used by the AI art director and --theme-file)."""
    palettes = [Palette.from_hex(p["bg"], p["fill"], p["primary"], p["secondary"], p.get("ground"))
                for p in data["palettes"]]
    if not palettes:
        raise ValueError("theme needs at least one palette")
    style = data.get("bg_style", "city")
    if style not in BG_STYLES:
        style = "city"
    return Theme(
        name=data.get("name", "custom"),
        palettes=palettes,
        bg_style=style,
        particle_density=min(1.0, max(0.0, float(data.get("particle_density", 0.5)))),
        glow_opacity=min(1.0, max(0.1, float(data.get("glow_opacity", 0.8)))),
        particle_shapes=tuple(s for s in data.get("particle_shapes", ()) if s in PARTICLE_SHAPE_NAMES) or ("dot", "dot", "square"),
        description=data.get("description", ""),
        section_moods=[p.get("mood", "") for p in data["palettes"]],
    )
