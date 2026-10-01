import base64
import zlib

from gdautodeco.level import (ColorChannel, GmdFile, Level, LocalLevels, decode_level_string, decrypt_save,
                              encode_level_string, encrypt_save)
from gdautodeco.sample import sample_level

RAW = "kS38,1_10_2_20_3_30_6_1000_7_1|,kA2,0,kA4,0;1,1,2,15,3,15;1,8,2,45,3,15,6,180;"


def test_level_string_round_trip():
    encoded = encode_level_string(RAW)
    assert encoded.startswith("H4sI")  # gzip, like the game writes
    assert decode_level_string(encoded) == RAW


def test_decodes_zlib_and_raw_strings():
    zlib_encoded = base64.urlsafe_b64encode(zlib.compress(RAW.encode())).decode()
    assert zlib_encoded.startswith("eJ")  # older server levels use zlib
    assert decode_level_string(zlib_encoded) == RAW
    assert decode_level_string(RAW) == RAW


def test_parse_and_serialize_keeps_unknown_keys():
    level = Level.from_raw(RAW.replace("6,180", "6,180,999,abc"))
    assert level.objects[1]["999"] == "abc"
    assert Level.from_raw(level.to_raw()).objects == level.objects
    assert level.header["kA2"] == "0"


def test_color_channels():
    level = Level.from_raw(RAW)
    colors = level.colors()
    assert (colors[1000].r, colors[1000].g, colors[1000].b) == (10, 20, 30)
    colors[5] = ColorChannel(5, 1, 2, 3, opacity=0.5, blending=True)
    level.set_colors(colors)
    again = Level.from_raw(level.to_raw()).colors()
    assert again[5].blending and again[5].opacity == 0.5 and (again[5].r, again[5].g, again[5].b) == (1, 2, 3)


def test_gmd_round_trip_preserves_other_fields(tmp_path):
    gmd = GmdFile.new(sample_level(), "Test & Co")
    gmd = GmdFile(gmd.text.replace("</dict>", "<k>k45</k><i>123</i></dict>"))
    path = tmp_path / "a.gmd"
    gmd.save(path)
    loaded = GmdFile.load(path)
    assert loaded.name == "Test & Co"
    assert loaded.level().to_raw() == sample_level().to_raw()
    small = Level.from_raw(RAW)
    updated = loaded.with_level(small, name="New")
    assert updated.level().to_raw() == RAW and updated.name == "New"
    assert "<k>k45</k><i>123</i>" in updated.text


def _save_xml(levels):
    entries = "".join(
        f"<k>k_{n}</k><d><k>kCEK</k><i>4</i><k>k1</k><i>{100 + n}</i><k>k2</k><s>{name}</s>"
        f"<k>k4</k><s>{encode_level_string(raw)}</s><k>k14</k><t /></d>"
        for n, (name, raw) in enumerate(levels))
    return (f'<?xml version="1.0"?><plist version="1.0" gjver="2.0"><dict><k>LLM_01</k><d><k>_isArr</k><t />'
            f"{entries}</d><k>LLM_02</k><i>35</i></dict></plist>")


def test_save_file_add_copy(tmp_path):
    path = tmp_path / "CCLocalLevels.dat"
    path.write_bytes(encrypt_save(_save_xml([("First", RAW), ("Second", RAW.replace("45", "75"))])))
    save = LocalLevels.load(path)
    assert save.names() == ["First", "Second"]
    assert save.level("Second").objects[1]["2"] == "75"

    decorated = Level.from_raw(RAW + "1,211,2,15,3,15;")
    save.add_copy("Second", "Second (deco)", decorated)
    backup = save.save(path)
    assert backup is not None and backup.exists()

    reloaded = LocalLevels.load(path)
    assert reloaded.names() == ["Second (deco)", "First", "Second"]
    assert reloaded.level("Second").objects[1]["2"] == "75"            # original untouched
    assert reloaded.level("Second (deco)").objects[-1]["1"] == "211"
    copy = reloaded.find("Second (deco)")
    keys = [el.text for el in list(copy)[0::2]]
    assert "k1" not in keys and "k14" not in keys                      # fresh local level
    assert "<k>LLM_02</k><i>35</i>" in decrypt_save(path.read_bytes())


def test_decrypt_tolerates_trailing_nulls():
    data = encrypt_save("<?xml version=\"1.0\"?><plist><dict></dict></plist>") + b"\x0b\x0b"
    assert "plist" in decrypt_save(data)
