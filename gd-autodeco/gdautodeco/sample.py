"""A small hand-made gameplay layout (default blocks only) for demos and tests."""

from __future__ import annotations

from .level import Level

HEADER = (
    "kS38,1_40_2_125_3_255_11_255_12_255_13_255_4_-1_6_1000_7_1_15_1_18_0_8_1|"
    "1_0_2_102_3_255_11_255_12_255_13_255_4_-1_6_1001_7_1_15_1_18_0_8_1|,"
    "kA13,0,kA15,0,kA16,0,kA14,,kA6,0,kA7,0,kA25,0,kA17,0,kA18,0,kS39,0,kA2,0,kA3,0,kA8,0,kA4,0,"
    "kA9,0,kA10,0,kA22,0,kA23,0,kA24,0,kA27,1,kA40,1,kA41,1,kA42,1,kA28,0,kA29,0,kA31,1,kA32,1,"
    "kA36,0,kA43,0,kA44,0,kA45,1,kA33,1,kA34,1,kA35,0,kA37,1,kA38,1,kA39,1,kA19,0,kA26,0,kA20,0,kA21,0,kA11,0"
)


class _Builder:
    def __init__(self):
        self.objs: list[str] = []

    def obj(self, oid: int, x: float, y: float, extra: str = "") -> None:
        self.objs.append(f"1,{oid},2,{x:g},3,{y:g}{extra}")

    def block(self, i: int, j: int) -> None:
        self.obj(1, 30 * i + 15, 30 * j + 15)

    def blocks(self, i0: int, i1: int, j0: int, j1: int) -> None:
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                self.block(i, j)

    def spike(self, i: int, j: int, down: bool = False) -> None:
        self.obj(8, 30 * i + 15, 30 * j + 15, ",6,180" if down else "")

    def small_spike(self, i: int, j: int) -> None:
        self.obj(39, 30 * i + 15, 30 * j + 6)

    def slab(self, i: int, j: int) -> None:
        self.obj(40, 30 * i + 15, 30 * j + 23)


def sample_level() -> Level:
    b = _Builder()
    # --- cube intro -------------------------------------------------------------
    b.spike(8, 0)
    b.blocks(12, 14, 0, 0)
    b.spike(15, 0)
    b.blocks(18, 19, 0, 1)
    b.spike(20, 0); b.spike(21, 0)
    b.blocks(22, 24, 0, 2)
    b.blocks(25, 27, 0, 0)  # step down -> inner corners
    b.small_spike(28, 0)
    b.obj(36, 31 * 30 + 15, 2 * 30 + 15)  # yellow orb
    b.spike(30, 0); b.spike(31, 0); b.spike(32, 0)
    b.blocks(34, 38, 2, 2)    # floating platform
    b.spike(36, 3)
    b.slab(40, 3); b.slab(41, 3)
    b.blocks(43, 44, 0, 4)    # pillar
    b.blocks(45, 47, 3, 4)    # L-shape overhang
    b.spike(46, 0); b.spike(47, 0)
    b.obj(35, 50 * 30 + 15, 2)  # yellow pad
    b.blocks(53, 58, 3, 3)
    b.blocks(57, 58, 0, 2)
    b.spike(55, 4)
    b.blocks(61, 63, 0, 1)
    b.blocks(62, 63, 2, 3)
    # --- ship -------------------------------------------------------------------
    b.obj(13, 68 * 30 + 15, 4 * 30 + 15)
    floor = [0, 0, 1, 1, 2, 3, 3, 2, 1, 0, 0, 1, 2, 2, 1, 0, 0, 0, 1, 3, 4, 3, 1, 0, 0, 1, 2, 1, 0, 0,
             0, 1, 2, 3, 3, 2, 1, 1, 0, 0]
    for k, h in enumerate(floor):
        i = 70 + k
        if h:
            b.blocks(i, i, 0, h - 1)
        ceil = 10 - (3 if 18 <= k <= 24 else (1 if k % 9 < 4 else 0))
        b.blocks(i, i, ceil, 10)
        if k in (6, 13, 27, 34):
            b.spike(i, h)
        if k in (10, 31):
            b.spike(i, ceil - 1, down=True)
    # --- fast cube finale --------------------------------------------------------
    b.obj(12, 111 * 30 + 15, 2 * 30 + 15)
    b.obj(202, 112 * 30 + 15, 1 * 30 + 15)
    b.blocks(115, 120, 0, 0)
    b.spike(118, 1)
    b.blocks(123, 124, 0, 2)
    b.spike(125, 0); b.spike(126, 0)
    b.blocks(127, 132, 0, 1)
    b.blocks(130, 132, 2, 4)
    b.spike(133, 0); b.spike(134, 0); b.spike(135, 0)
    b.obj(36, 134 * 30 + 15, 3 * 30 + 15)
    b.blocks(138, 145, 3, 3)
    b.spike(141, 4)
    b.slab(147, 2); b.slab(148, 2); b.slab(149, 2)
    b.blocks(152, 160, 0, 0)
    b.blocks(156, 160, 1, 2)
    b.small_spike(154, 1)
    return Level.from_raw(HEADER + ";" + ";".join(b.objs) + ";")
