"""Command line interface: ``python -m gdautodeco --help``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .analyze import analyze
from .decorate import Options, decorate
from .level import GmdFile, Level, LocalLevels
from .themes import THEMES, theme_from_dict


def _load(path: Path, level_name: str | None) -> tuple[Level, str]:
    suffix = path.suffix.lower()
    if suffix == ".gmd":
        gmd = GmdFile.load(path)
        return gmd.level(), gmd.name
    if suffix == ".dat":
        if not level_name:
            sys.exit("a save file holds many levels: pass --level NAME (see `levels` to list them)")
        return LocalLevels.load(path).level(level_name), level_name
    return Level.from_string(path.read_text(encoding="utf-8")), path.stem


def _save(src: Path, out: Path, level: Level, source_name: str, new_name: str) -> None:
    suffix = src.suffix.lower()
    if suffix == ".gmd":
        GmdFile.load(src).with_level(level, name=new_name).save(out)
    elif suffix == ".dat":
        save = LocalLevels.load(src)
        save.add_copy(source_name, new_name, level)
        backup = save.save(out, backup=True)
        print(f"Added '{new_name}' to {out} (your original level is unchanged).")
        if backup:
            print(f"Backup of the previous save: {backup}")
        print("Make sure Geometry Dash was closed while this ran, or it will overwrite the save on exit.")
        return
    else:
        out.write_text(level.to_string(), encoding="utf-8")
    print(f"Wrote {out}")


def _default_out(src: Path) -> Path:
    if src.suffix.lower() == ".dat":
        return src
    return src.with_name(f"{src.stem}-decorated{src.suffix or '.txt'}")


def _blocks(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    a, b = text.split(":")
    return int(a), int(b)


def cmd_decorate(args) -> None:
    src = Path(args.input)
    level, name = _load(src, args.level)
    layout = analyze(level)
    if args.prompt:
        from .art_director import theme_from_prompt
        print("Asking Claude for a theme...")
        try:
            theme = theme_from_prompt(args.prompt, layout)
        except Exception as exc:  # network/auth/refusal: explain and stop
            sys.exit(f"AI art director failed: {exc}\n(Use --theme NAME to decorate without the AI.)")
        print(f"Theme '{theme.name}': {theme.description}")
    elif args.theme_file:
        theme = theme_from_dict(json.loads(Path(args.theme_file).read_text()))
    else:
        if args.theme not in THEMES:
            sys.exit(f"unknown theme {args.theme!r}; choose from: {', '.join(THEMES)}")
        theme = THEMES[args.theme]
    if args.save_theme:
        data = asdict(theme)
        data["palettes"] = [{k: "#%02x%02x%02x" % v for k, v in p.items() if v} for p in data["palettes"]]
        Path(args.save_theme).write_text(json.dumps(data, indent=2))

    options = Options(
        seed=args.seed, bpm=args.bpm, first_beat=args.first_beat,
        structures=not args.no_structures, background=not args.no_background,
        particles=not args.no_particles, color_changes=not args.no_color_changes,
    )
    try:
        decorated, report = decorate(level, theme, options)
    except ValueError as exc:
        sys.exit(f"Can't decorate this level: {exc}")
    print(report.summary())
    out = Path(args.output) if args.output else _default_out(src)
    _save(src, out, decorated, name, args.name or f"{name} (deco)")
    if args.preview:
        from .preview import render
        render(decorated, args.preview, blocks=_blocks(args.blocks))
        print(f"Preview: {args.preview}")


def cmd_preview(args) -> None:
    from .preview import render
    level, _ = _load(Path(args.input), args.level)
    render(level, args.output, blocks=_blocks(args.blocks))
    print(f"Preview: {args.output}")


def cmd_themes(_args) -> None:
    for theme in THEMES.values():
        print(f"{theme.name:<8} {theme.bg_style:<9} {theme.description}")


def cmd_levels(args) -> None:
    for name in LocalLevels.load(args.save).names():
        print(name)


def cmd_sample(args) -> None:
    from .sample import sample_level
    GmdFile.new(sample_level(), "AutoDeco Sample").save(args.output)
    print(f"Wrote {args.output}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="gdautodeco", description="Procedurally decorate Geometry Dash layouts.")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("decorate", help="decorate a level (.gmd, CCLocalLevels.dat, or a level-string file)")
    d.add_argument("input")
    d.add_argument("-o", "--output", help="output file (default: <input>-decorated.gmd; save files are updated in place with a backup)")
    d.add_argument("--level", help="level name inside CCLocalLevels.dat")
    d.add_argument("--name", help="name for the decorated level (default: '<name> (deco)')")
    d.add_argument("--theme", default="neon", help=f"built-in theme: {', '.join(THEMES)}")
    d.add_argument("--theme-file", help="JSON theme file (see --save-theme)")
    d.add_argument("--prompt", help="describe the look you want and let Claude pick the theme (needs `pip install anthropic` + API key)")
    d.add_argument("--save-theme", help="write the theme that was used to this JSON file")
    d.add_argument("--seed", type=int, default=1, help="change for a different random layout of the same style")
    d.add_argument("--bpm", type=float, help="song tempo: adds glow pulses on the beat")
    d.add_argument("--first-beat", type=float, default=0.0, help="seconds from level start to the first beat")
    d.add_argument("--no-structures", action="store_true", help="don't restyle the gameplay blocks")
    d.add_argument("--no-background", action="store_true")
    d.add_argument("--no-particles", action="store_true")
    d.add_argument("--no-color-changes", action="store_true", help="one palette for the whole level")
    d.add_argument("--preview", help="also render a PNG preview")
    d.add_argument("--blocks", help="preview only blocks A:B, e.g. 0:120")
    d.set_defaults(func=cmd_decorate)

    v = sub.add_parser("preview", help="render a PNG preview of a level")
    v.add_argument("input")
    v.add_argument("-o", "--output", default="preview.png")
    v.add_argument("--level")
    v.add_argument("--blocks", help="only blocks A:B, e.g. 0:120")
    v.set_defaults(func=cmd_preview)

    t = sub.add_parser("themes", help="list built-in themes")
    t.set_defaults(func=cmd_themes)

    lv = sub.add_parser("levels", help="list the editor levels in CCLocalLevels.dat")
    lv.add_argument("save")
    lv.set_defaults(func=cmd_levels)

    s = sub.add_parser("sample", help="write a small undecorated demo layout")
    s.add_argument("-o", "--output", default="sample.gmd")
    s.set_defaults(func=cmd_sample)

    args = p.parse_args(argv)
    args.func(args)
