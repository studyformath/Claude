from PIL import Image

from gdautodeco.cli import main
from gdautodeco.level import GmdFile, LocalLevels, encrypt_save
from gdautodeco.sample import sample_level


def test_sample_decorate_preview(tmp_path, capsys):
    sample = tmp_path / "sample.gmd"
    main(["sample", "-o", str(sample)])
    out = tmp_path / "out.gmd"
    png = tmp_path / "out.png"
    main(["decorate", str(sample), "-o", str(out), "--theme", "sunset", "--bpm", "128", "--preview", str(png)])
    decorated = GmdFile.load(out)
    assert decorated.name == "AutoDeco Sample (deco)"
    assert len(decorated.level().objects) > 3 * len(sample_level().objects)
    assert Image.open(png).width > 500
    assert "editor layer" in capsys.readouterr().out


def test_decorate_into_save_file(tmp_path):
    level = sample_level()
    xml = ('<?xml version="1.0"?><plist version="1.0" gjver="2.0"><dict><k>LLM_01</k><d><k>_isArr</k><t />'
           f"<k>k_0</k><d><k>kCEK</k><i>4</i><k>k2</k><s>My Layout</s><k>k4</k><s>{level.to_string()}</s></d>"
           "</d></dict></plist>")
    save = tmp_path / "CCLocalLevels.dat"
    save.write_bytes(encrypt_save(xml))
    main(["levels", str(save)])
    main(["decorate", str(save), "--level", "My Layout", "--theme", "toxic"])
    reloaded = LocalLevels.load(save)
    assert reloaded.names() == ["My Layout (deco)", "My Layout"]
    assert reloaded.level("My Layout").to_raw() == level.to_raw()
    assert list(tmp_path.glob("CCLocalLevels.dat.backup-*"))


def test_saved_theme_reproduces_output(tmp_path):
    sample = tmp_path / "s.gmd"
    main(["sample", "-o", str(sample)])
    theme = tmp_path / "theme.json"
    main(["decorate", str(sample), "-o", str(tmp_path / "a.gmd"), "--theme", "vapor", "--save-theme", str(theme)])
    main(["decorate", str(sample), "-o", str(tmp_path / "b.gmd"), "--theme-file", str(theme)])
    assert GmdFile.load(tmp_path / "a.gmd").level().to_raw() == GmdFile.load(tmp_path / "b.gmd").level().to_raw()
