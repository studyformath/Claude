import json
from types import SimpleNamespace

import pytest

from gdautodeco import objects as O
from gdautodeco.analyze import analyze
from gdautodeco.decorate import Options, decorate
from gdautodeco.level import Level
from gdautodeco.sample import sample_level
from gdautodeco.themes import THEMES, theme_from_dict

HEADER = "kS38,1_0_2_0_3_0_6_1000_7_1|,kA2,0,kA4,0"
GAMEPLAY_KEYS = {O.ID, O.X, O.Y, O.ROTATION, O.FLIP_X, O.FLIP_Y, O.SCALE, O.SCALE_X, O.SCALE_Y, "57", "121"}


def blocks_level(cells, extra=""):
    objs = ";".join(f"1,1,2,{30 * i + 15},3,{30 * j + 15}" for i, j in cells)
    return Level.from_raw(f"{HEADER};{objs};{extra}")


def added(level, decorated):
    return decorated.objects[len(level.objects):]


def by_kind(objs, oid):
    return [o for o in objs if o[O.ID] == str(oid)]


def test_gameplay_objects_keep_ids_positions_and_hitboxes():
    level = sample_level()
    decorated, _ = decorate(level, THEMES["neon"], Options(bpm=140))
    for before, after in zip(level.objects, decorated.objects):
        for key in GAMEPLAY_KEYS:
            assert before.get(key) == after.get(key)
        changed = {k for k in after if before.get(k) != after.get(k)}
        assert changed <= {O.NO_GLOW, O.MAIN_COLOR}  # purely visual
    gameplay_ids = O.SOLID_BLOCKS | O.SLABS | O.HAZARDS | O.ORBS_AND_PADS | set(O.GAMEMODE_PORTALS) | set(O.SPEED_PORTALS)
    assert not [o for o in added(level, decorated) if int(o[O.ID]) in gameplay_ids]


def test_single_block_geometry():
    level = blocks_level([(5, 3)])
    new = added(level, decorate(level, THEMES["neon"], Options(background=False, particles=False))[0])
    fills = by_kind(new, O.FILL_SQUARE)
    assert [(o[O.X], o[O.Y], o[O.Z_LAYER]) for o in fills] == [("165", "105", str(O.T2))]
    lines = {(o[O.X], o[O.Y], o.get(O.ROTATION, "0")) for o in by_kind(new, O.OUTLINE_LINE)}
    assert lines == {("165", "119.25", "0"), ("165", "90.75", "180"), ("150.75", "105", "270"), ("179.25", "105", "90")}
    glows = {(o[O.X], o[O.Y], o.get(O.ROTATION, "0")) for o in by_kind(new, O.GLOW_EDGE)}
    assert glows == {("165", "130", "0"), ("165", "80", "180"), ("140", "105", "270"), ("190", "105", "90")}
    corners = {(o[O.X], o[O.Y], o.get(O.FLIP_X, "0"), o.get(O.FLIP_Y, "0")) for o in by_kind(new, O.GLOW_CORNER)}
    assert corners == {("140", "130", "0", "0"), ("190", "130", "1", "0"), ("140", "80", "0", "1"), ("190", "80", "1", "1")}
    assert not by_kind(new, O.OUTLINE_CORNER_DOT)


def test_runs_are_merged_and_ground_edges_skipped():
    level = blocks_level([(i, 0) for i in range(3)])
    new = added(level, decorate(level, THEMES["neon"], Options(background=False, particles=False))[0])
    fill = by_kind(new, O.FILL_SQUARE)
    assert len(fill) == 1 and fill[0][O.SCALE_X] == "3" and fill[0][O.X] == "45"
    lines = by_kind(new, O.OUTLINE_LINE)
    assert sorted(o.get(O.ROTATION, "0") for o in lines) == ["0", "270", "90"]  # no bottom line on the ground
    top = [o for o in lines if O.ROTATION not in o][0]
    assert top[O.SCALE_X] == "3"


def test_long_runs_are_split():
    level = blocks_level([(i, 2) for i in range(20)])
    new = added(level, decorate(level, THEMES["neon"], Options(background=False, particles=False))[0])
    fills = by_kind(new, O.FILL_SQUARE)
    assert sorted(float(o[O.SCALE_X]) for o in fills) == [6, 7, 7]
    assert sum(float(o[O.SCALE_X]) for o in fills) == 20


@pytest.mark.parametrize("cells, expected", [
    # Wall on the left: the outline gap is in the top-right of cell (0,0) -> dot rotated 90.
    ([(0, 1), (0, 0), (1, 0)], ("15", "15", "90")),
    # Wall on the right: the gap is in the top-left of cell (1,0) -> unrotated dot.
    ([(1, 1), (1, 0), (0, 0)], ("45", "15", "0")),
])
def test_inner_corner_patch(cells, expected):
    level = blocks_level(cells)
    new = added(level, decorate(level, THEMES["neon"], Options(background=False, particles=False))[0])
    dots = by_kind(new, O.OUTLINE_CORNER_DOT)
    assert [(o[O.X], o[O.Y], o.get(O.ROTATION, "0")) for o in dots] == [expected]


def test_off_grid_blocks_and_slopes_are_recolored_not_covered():
    level = Level.from_raw(f"{HEADER};1,1,2,15,3,15;1,1,2,52,3,15,21,1004;1,1,2,105,3,15,24,9;1,1743,2,135,3,15;"
                           "1,1,2,180,3,30,128,2,129,2;")
    layout = analyze(level)
    assert layout.solid == {(0, 0), (5, 0), (5, 1), (6, 0), (6, 1)}   # the scaled 2x2 block is on-grid
    assert len(layout.loose_objects) == 3                               # half-offset, T3 layer, slope
    decorated, report = decorate(level, THEMES["neon"], Options(background=False, particles=False))
    outline = str(report.channels["outline"])
    assert [decorated.objects[i].get(O.MAIN_COLOR) for i in (1, 2, 3)] == [outline] * 3  # 21=1004 is "default"
    assert O.MAIN_COLOR not in decorated.objects[0]
    new = added(level, decorated)
    overlays = {(o[O.ID], o[O.X], o[O.Y]) for o in new if o[O.X] in ("52", "105")}
    assert overlays == {("211", "52", "15"), ("467", "52", "15"), ("211", "105", "15"), ("467", "105", "15")}


def test_channels_avoid_existing_ones_and_triggers_keep_blending():
    level = blocks_level([(0, 0)], extra="1,8,2,100,3,15,21,1;1,899,2,0,3,0,23,2;")
    decorated, report = decorate(level, THEMES["neon"], Options())
    deco_channels = {v for k, v in report.channels.items() if v < 1000}
    assert not deco_channels & {1, 2}
    colors = decorated.colors()
    assert colors[report.channels["glow"]].blending
    assert colors[report.channels["fill"]].blending is False


def test_sections_and_color_triggers_follow_gamemodes():
    level = sample_level()
    layout = analyze(level)
    assert [s.mode for s in layout.sections] == ["cube", "ship", "cube"]
    decorated, report = decorate(level, THEMES["neon"], Options())
    triggers = by_kind(added(level, decorated), O.COLOR_TRIGGER)
    xs = sorted({float(t[O.X]) for t in triggers})
    assert xs == [layout.sections[1].x_start, layout.sections[2].x_start]
    glow_triggers = [t for t in triggers if t["23"] == str(report.channels["glow"])]
    assert glow_triggers and all(t.get("17") == "1" for t in glow_triggers)


def test_time_to_x_follows_speed_portals():
    level = Level.from_raw(f"{HEADER};1,1,2,15,3,15;1,202,2,3000,3,45;1,1,2,6000,3,15;")
    layout = analyze(level)
    t_portal = 3000 / O.SPEED_UNITS_PER_SECOND[0]
    assert layout.x_at_time(t_portal) == pytest.approx(3000)
    assert layout.x_at_time(t_portal + 1) == pytest.approx(3000 + O.SPEED_UNITS_PER_SECOND[2])
    assert layout.time_at_x(3000 + O.SPEED_UNITS_PER_SECOND[2]) == pytest.approx(t_portal + 1)


def test_beat_pulses_cover_the_level():
    level = sample_level()
    decorated, _ = decorate(level, THEMES["neon"], Options(bpm=120))
    pulses = by_kind(added(level, decorated), O.PULSE_TRIGGER)
    xs = sorted({float(p[O.X]) for p in pulses})
    layout = analyze(level)
    beats = layout.time_at_x(layout.max_x) * 2  # 120 bpm = 2 beats/s
    assert 0.5 * beats <= len(xs) <= beats + 12
    assert all(p["51"] for p in pulses)


def test_deterministic_and_seeded():
    a = decorate(sample_level(), THEMES["frost"], Options(seed=7))[0].to_raw()
    b = decorate(sample_level(), THEMES["frost"], Options(seed=7))[0].to_raw()
    c = decorate(sample_level(), THEMES["frost"], Options(seed=8))[0].to_raw()
    assert a == b and a != c


@pytest.mark.parametrize("name", list(THEMES))
def test_every_theme_runs(name):
    decorated, report = decorate(sample_level(), THEMES[name], Options(bpm=128))
    assert report.added["fill"] and report.added["glow"]
    assert all(o[O.EDITOR_LAYER] == str(report.editor_layer) for o in decorated.objects[report.original_objects:])
    Level.from_string(decorated.to_string())  # still encodes/decodes


def test_theme_from_dict_validates():
    theme = theme_from_dict({"name": "x", "bg_style": "nope", "particle_shapes": ["dot", "bogus"],
                             "palettes": [{"bg": "#000000", "fill": "#111111", "primary": "#ff0000", "secondary": "#00ff00"}]})
    assert theme.bg_style == "city" and theme.particle_shapes == ("dot",)
    with pytest.raises(ValueError):
        theme_from_dict({"palettes": [{"bg": "red", "fill": "#111111", "primary": "#ff0000", "secondary": "#00ff00"}]})


def test_art_director_parses_structured_output(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    from gdautodeco import art_director

    payload = {"name": "haunted", "description": "spooky", "bg_style": "pillars", "particle_density": 0.4,
               "glow_opacity": 0.7, "particle_shapes": ["dot", "cross"],
               "palettes": [{"mood": m, "bg": "#0a0612", "fill": "#140b22", "primary": "#9dff5c",
                             "secondary": "#c79bff", "ground": "#1c1030"} for m in ("calm", "tense", "finale")]}
    calls = []

    class FakeMessages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    class FakeClient:
        beta = SimpleNamespace(messages=FakeMessages())

    monkeypatch.setattr(anthropic, "Anthropic", lambda: FakeClient())
    theme = art_director.theme_from_prompt("haunted castle", analyze(sample_level()))
    assert theme.name == "haunted" and len(theme.palettes) == 3 and theme.bg_style == "pillars"
    assert calls[0]["model"] == art_director.MODEL
    assert calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert "3 sections" in calls[0]["messages"][0]["content"]
    decorate(sample_level(), theme, Options())
