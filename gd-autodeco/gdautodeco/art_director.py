"""Optional: let Claude choose the theme from a plain-English vibe ("haunted neon castle").

The language model never places objects - it is bad at precise coordinates and a level has
thousands of them. It does what it is good at (art direction: palettes, mood per section,
background style) and the deterministic engine in ``decorate.py`` does the placement.

Needs ``pip install anthropic`` and an API key (``ANTHROPIC_API_KEY``) or ``ant auth login``.
"""

from __future__ import annotations

import json

from .analyze import Layout
from .themes import BG_STYLES, PARTICLE_SHAPE_NAMES, Theme, theme_from_dict

MODEL = "claude-opus-5-5"

_COLOR = {"type": "string", "description": "hex color like #1a2b3c"}
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "bg_style": {"type": "string", "enum": list(BG_STYLES)},
        "particle_density": {"type": "number", "description": "0 (none) to 1 (lots)"},
        "glow_opacity": {"type": "number", "description": "0.1 (subtle) to 1 (intense)"},
        "particle_shapes": {"type": "array", "items": {"type": "string", "enum": list(PARTICLE_SHAPE_NAMES)}},
        "palettes": {
            "type": "array",
            "description": "one palette per level section, in order",
            "items": {
                "type": "object",
                "properties": {
                    "mood": {"type": "string"},
                    "bg": _COLOR, "fill": _COLOR, "primary": _COLOR, "secondary": _COLOR, "ground": _COLOR,
                },
                "required": ["mood", "bg", "fill", "primary", "secondary", "ground"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["name", "description", "bg_style", "particle_density", "glow_opacity", "particle_shapes", "palettes"],
    "additionalProperties": False,
}

SYSTEM = """You are the art director for a Geometry Dash level decorator.
You pick colors and style; a separate engine places every object.

Color roles in each palette:
- bg: sky/background. Usually dark so glows pop.
- fill: the inside of the gameplay blocks. Must contrast clearly with bg so players can read the layout.
- primary: block outlines and glow around them. The brightest, most saturated color.
- secondary: particles and small background details. Complements primary.
- ground: the floor below the level.

Rules: gameplay readability beats prettiness. Keep fill darker than primary. Spikes are drawn in a
light tint of primary, so primary must stand out against fill and bg. Give each section a palette
that fits its gamemode and intensity, and make consecutive sections feel like one level
(shared hues or a gradual shift). Return exactly one palette per section."""


def describe_layout(layout: Layout) -> str:
    lines = [f"The level has {len(layout.sections)} sections:"]
    for s in layout.sections:
        seconds = layout.time_at_x(s.x_end) - layout.time_at_x(s.x_start)
        lines.append(f"- section {s.index}: {s.mode} gamemode, about {seconds:.0f} s long, "
                     f"intensity {s.intensity:.2f} (1 = the hardest/busiest part)")
    return "\n".join(lines)


def theme_from_prompt(prompt: str, layout: Layout, model: str = MODEL) -> Theme:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("the AI art director needs the Anthropic SDK: pip install anthropic") from exc

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": f"Vibe: {prompt}\n\n{describe_layout(layout)}"}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this description; try wording it differently")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("the theme response was cut off; try again")
    text = next(block.text for block in response.content if block.type == "text")
    return theme_from_dict(json.loads(text))
