"""Reading and writing Geometry Dash levels.

Supported containers:
  * raw level strings (compressed ``H4sI...``/``eJ...`` or already decoded)
  * ``.gmd`` files (the single-level export format used by GDShare / Geode mods)
  * ``CCLocalLevels.dat`` (the Windows/Android save file holding all editor levels)

Format references: https://github.com/Wyliemaster/gddocs
"""

from __future__ import annotations

import base64
import gzip
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path


# --------------------------------------------------------------------------
# Level string codec
# --------------------------------------------------------------------------

def decode_level_string(data: str) -> str:
    """Return the raw ``header;obj;obj;...`` text for an encoded or raw level string."""
    data = data.strip()
    if _looks_raw(data):
        return data
    padded = data + "=" * (-len(data) % 4)
    compressed = base64.urlsafe_b64decode(padded.encode())
    # wbits=47 lets zlib auto-detect both gzip (H4sI...) and zlib (eJ...) streams.
    return zlib.decompress(compressed, 47).decode("utf-8")


def encode_level_string(raw: str) -> str:
    """Compress a raw level string the way Geometry Dash stores it (gzip + url-safe base64)."""
    return base64.urlsafe_b64encode(gzip.compress(raw.encode("utf-8"), mtime=0)).decode()


def _looks_raw(data: str) -> bool:
    return data.startswith("kS") or data.startswith("kA") or data.startswith("1,") or ";1," in data[:4000]


# --------------------------------------------------------------------------
# Level model
# --------------------------------------------------------------------------

@dataclass
class ColorChannel:
    """One entry of the level's initial color list (header key ``kS38``)."""

    channel: int
    r: int
    g: int
    b: int
    opacity: float = 1.0
    blending: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str) -> "ColorChannel":
        parts = text.split("_")
        props = dict(zip(parts[0::2], parts[1::2]))
        return cls(
            channel=int(props.pop("6", "0")),
            r=int(float(props.pop("1", "255"))),
            g=int(float(props.pop("2", "255"))),
            b=int(float(props.pop("3", "255"))),
            opacity=float(props.pop("7", "1")),
            blending=props.pop("5", "0") == "1",
            extra=props,
        )

    def serialize(self) -> str:
        props = {
            "1": str(self.r), "2": str(self.g), "3": str(self.b),
            "11": "255", "12": "255", "13": "255", "4": "-1",
            "6": str(self.channel), "7": fmt_number(self.opacity),
            "15": "1", "18": "0", "8": "1",
        }
        if self.blending:
            props["5"] = "1"
        # Keep settings we don't model (copy-color, HSV, ...) unless we overrode them.
        for k, v in self.extra.items():
            props.setdefault(k, v)
        if not self.blending:
            props.pop("5", None)
        return "_".join(f"{k}_{v}" for k, v in props.items())


class Level:
    """A parsed level: an ordered header plus a list of objects.

    Objects are plain ``dict[str, str]`` keyed by the level-string property id
    (``"1"`` = object id, ``"2"``/``"3"`` = x/y, ...). Unknown properties are kept
    verbatim so round-tripping never loses data.
    """

    def __init__(self, header: dict[str, str], objects: list[dict[str, str]]):
        self.header = header
        self.objects = objects

    # ---- parsing -------------------------------------------------------
    @classmethod
    def from_raw(cls, raw: str) -> "Level":
        chunks = raw.split(";")
        header_parts = chunks[0].split(",")
        header = dict(zip(header_parts[0::2], header_parts[1::2]))
        objects = []
        for chunk in chunks[1:]:
            if not chunk:
                continue
            parts = chunk.split(",")
            obj = dict(zip(parts[0::2], parts[1::2]))
            if "1" in obj:
                objects.append(obj)
        return cls(header, objects)

    @classmethod
    def from_string(cls, data: str) -> "Level":
        return cls.from_raw(decode_level_string(data))

    # ---- serializing ---------------------------------------------------
    def to_raw(self) -> str:
        header = ",".join(f"{k},{v}" for k, v in self.header.items())
        body = ";".join(",".join(f"{k},{v}" for k, v in obj.items()) for obj in self.objects)
        return f"{header};{body};"

    def to_string(self) -> str:
        return encode_level_string(self.to_raw())

    # ---- colors --------------------------------------------------------
    def colors(self) -> dict[int, ColorChannel]:
        text = self.header.get("kS38", "")
        out: dict[int, ColorChannel] = {}
        for entry in text.split("|"):
            if entry:
                ch = ColorChannel.parse(entry)
                out[ch.channel] = ch
        return out

    def set_colors(self, channels: dict[int, ColorChannel]) -> None:
        self.header["kS38"] = "".join(ch.serialize() + "|" for ch in channels.values())

    def copy(self) -> "Level":
        return Level(dict(self.header), [dict(o) for o in self.objects])


def fmt_number(value: float) -> str:
    """Format a number the way GD writes them (no trailing zeros, no exponent)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


# --------------------------------------------------------------------------
# .gmd files
# --------------------------------------------------------------------------

_K4_RE = re.compile(r"(<k(?:ey)?>k4</k(?:ey)?>\s*<s(?:tring)?>)(.*?)(</s(?:tring)?>)", re.S)
_K2_RE = re.compile(r"(<k(?:ey)?>k2</k(?:ey)?>\s*<s(?:tring)?>)(.*?)(</s(?:tring)?>)", re.S)


@dataclass
class GmdFile:
    """A ``.gmd`` export. Everything except the level data and name is preserved byte-for-byte."""

    text: str

    @classmethod
    def load(cls, path: str | Path) -> "GmdFile":
        return cls(Path(path).read_text(encoding="utf-8"))

    @property
    def name(self) -> str:
        m = _K2_RE.search(self.text)
        return _xml_unescape(m.group(2)) if m else "Unnamed"

    def level(self) -> Level:
        m = _K4_RE.search(self.text)
        if not m:
            raise ValueError("no level data (k4) found in .gmd file")
        return Level.from_string(m.group(2))

    def with_level(self, level: Level, name: str | None = None) -> "GmdFile":
        text = _K4_RE.sub(lambda m: m.group(1) + level.to_string() + m.group(3), self.text, count=1)
        if name is not None:
            text = _K2_RE.sub(lambda m: m.group(1) + _xml_escape(name) + m.group(3), text, count=1)
        return GmdFile(text)

    @classmethod
    def new(cls, level: Level, name: str) -> "GmdFile":
        return cls(
            '<?xml version="1.0"?><plist version="1.0" gjver="2.0"><dict>'
            f"<k>kCEK</k><i>4</i><k>k2</k><s>{_xml_escape(name)}</s>"
            f"<k>k4</k><s>{level.to_string()}</s>"
            "<k>k13</k><t /><k>k21</k><i>2</i><k>k50</k><i>45</i>"
            "</dict></plist>"
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.text, encoding="utf-8")


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


# --------------------------------------------------------------------------
# CCLocalLevels.dat (Windows / Android save format)
# --------------------------------------------------------------------------

def decrypt_save(data: bytes) -> str:
    """XOR 11 -> url-safe base64 -> gzip, per gddocs 'localfiles_encrypt_decrypt'."""
    if data.lstrip().startswith(b"<?xml"):
        return data.decode("utf-8")  # already plain (some tools write it decoded)
    xored = bytes(b ^ 11 for b in data).rstrip(b"\x00").decode("ascii", "ignore")
    xored = xored.strip().replace("\n", "")
    padded = xored + "=" * (-len(xored) % 4)
    return zlib.decompress(base64.urlsafe_b64decode(padded), 47).decode("utf-8")


def encrypt_save(xml: str) -> bytes:
    b64 = base64.urlsafe_b64encode(gzip.compress(xml.encode("utf-8"), mtime=0))
    return bytes(b ^ 11 for b in b64)


class LocalLevels:
    """The editor levels inside ``CCLocalLevels.dat``."""

    def __init__(self, xml: str):
        self.root = ET.fromstring(xml)
        self.levels_dict = self._find_dict(self.root.find("dict"), "LLM_01")
        if self.levels_dict is None:
            raise ValueError("LLM_01 (local level list) not found in save file")

    @classmethod
    def load(cls, path: str | Path) -> "LocalLevels":
        return cls(decrypt_save(Path(path).read_bytes()))

    @staticmethod
    def _find_dict(d: ET.Element | None, key: str) -> ET.Element | None:
        if d is None:
            return None
        children = list(d)
        for k_el, v_el in zip(children[0::2], children[1::2]):
            if k_el.text == key:
                return v_el
        return None

    def _entries(self) -> list[tuple[ET.Element, ET.Element]]:
        children = list(self.levels_dict)
        return [(k, v) for k, v in zip(children[0::2], children[1::2]) if k.text and k.text.startswith("k_")]

    @staticmethod
    def _get(level_el: ET.Element, key: str) -> ET.Element | None:
        children = list(level_el)
        for k_el, v_el in zip(children[0::2], children[1::2]):
            if k_el.text == key:
                return v_el
        return None

    def names(self) -> list[str]:
        out = []
        for _, v in self._entries():
            name_el = self._get(v, "k2")
            out.append(name_el.text if name_el is not None and name_el.text else "Unnamed")
        return out

    def find(self, name: str) -> ET.Element:
        matches = [v for _, v in self._entries() if (self._get(v, "k2") is not None and self._get(v, "k2").text == name)]
        if not matches:
            raise KeyError(f"no editor level named {name!r}. Available: {', '.join(self.names()[:30])}")
        return matches[0]

    def level(self, name: str) -> Level:
        k4 = self._get(self.find(name), "k4")
        if k4 is None or not k4.text:
            raise ValueError(f"level {name!r} has no level data (open it in the editor once and save)")
        return Level.from_string(k4.text)

    def add_copy(self, source_name: str, new_name: str, level: Level) -> None:
        """Insert a decorated copy at the top of the list; the original level is left untouched."""
        src = self.find(source_name)
        copy = ET.fromstring(ET.tostring(src))
        children = list(copy)
        for k_el, v_el in list(zip(children[0::2], children[1::2])):
            # Drop the online id / verified / uploaded flags so the copy is a fresh local level.
            if k_el.text in ("k1", "k14", "k15"):
                copy.remove(k_el)
                copy.remove(v_el)
        self._get(copy, "k2").text = new_name
        k4 = self._get(copy, "k4")
        k4.text = level.to_string()
        # Shift k_0, k_1, ... down by one and insert the copy as k_0 (newest level first).
        entries = self._entries()
        for k_el, _ in entries:
            k_el.text = f"k_{int(k_el.text[2:]) + 1}"
        first_index = list(self.levels_dict).index(entries[0][0]) if entries else len(self.levels_dict)
        key_el = ET.Element("k")
        key_el.text = "k_0"
        self.levels_dict.insert(first_index, key_el)
        self.levels_dict.insert(first_index + 1, copy)

    def to_xml(self) -> str:
        return '<?xml version="1.0"?>' + ET.tostring(self.root, encoding="unicode")

    def save(self, path: str | Path, backup: bool = True) -> Path | None:
        path = Path(path)
        backup_path = None
        if backup and path.exists():
            backup_path = path.with_name(f"{path.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(path, backup_path)
        path.write_bytes(encrypt_save(self.to_xml()))
        return backup_path
