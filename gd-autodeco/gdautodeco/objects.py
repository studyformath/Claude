"""Object ids and property keys the decorator relies on.

Ids were cross-checked against the sprite tables of the open-source GDRWeb
renderer (https://github.com/iliasHDZ/GDRWeb) and against how creators place
them in ~400 rated levels (12M objects) from the public
``yusp48/geometry-dash-levels`` dataset.
"""

# ---- property keys ---------------------------------------------------------
ID, X, Y = "1", "2", "3"
FLIP_X, FLIP_Y, ROTATION = "4", "5", "6"
EDITOR_LAYER = "20"
MAIN_COLOR, DETAIL_COLOR = "21", "22"
Z_LAYER, Z_ORDER = "24", "25"
SCALE = "32"            # legacy uniform scale (pre-2.2)
SCALE_X, SCALE_Y = "128", "129"
NO_GLOW = "96"
HIGH_DETAIL = "103"
NO_TOUCH = "121"

# Z layers as stored in the level string.
B5, B4, B3, B2, B1, T1, T2, T3, T4 = -5, -3, -1, 1, 3, 5, 7, 9, 11

# ---- grid ------------------------------------------------------------------
UNIT = 30.0  # one grid block

# ---- gameplay objects ------------------------------------------------------
# Full 30x30 solid blocks commonly used for layouts (default block set + colorable variants).
SOLID_BLOCKS = {
    1, 2, 3, 4, 6, 7, 69, 70, 71, 72, 74, 75, 76, 77, 78, 81, 82, 83, 90, 91, 92, 93, 94, 95, 96,
    116, 117, 118, 119, 121, 122, 160, 161, 162, 163, 165, 166, 167, 168, 169,
    207, 208, 209, 210, 212, 213, 247, 248, 249, 250, 252, 253, 254, 255, 256, 257, 258,
    260, 261, 263, 264, 265, 267, 268, 269, 270, 271, 272, 274, 275,
}

# Half-height platforms (slabs) that sit in the top half of their cell.
SLABS = {40, 147, 369, 370, 1903, 1904, 1905}

# Slopes in the default-block style (outline drawn with the main color).
SLOPES = {289, 291, 294, 295, 299, 301, 309, 311, 315, 317, 321, 323, 331, 333, 337, 339, 343, 345, 353, 355,
          1743, 1744, 1745, 1746, 1747, 1748, 1749, 1906}

HAZARDS = {
    8, 39, 103, 392, 216, 217, 218, 458, 144, 145, 205, 459,     # spikes
    88, 89, 98, 183, 184, 185, 186, 187, 188, 397, 398, 399,     # saws
    678, 679, 680, 740, 741, 742, 1619, 1620,
    9, 61, 243, 244, 363, 364, 365, 366, 367, 368, 446, 447, 667, 989, 991,  # ground spikes
}

ORBS_AND_PADS = {35, 36, 67, 84, 140, 141, 1022, 1330, 1332, 1333, 1594, 1704, 1751, 3004, 3005, 3027}

GAMEMODES = ["cube", "ship", "ball", "ufo", "wave", "robot", "spider", "swing"]  # header kA2 order
GAMEMODE_PORTALS = {12: "cube", 13: "ship", 47: "ball", 111: "ufo", 660: "wave", 745: "robot", 1331: "spider", 1933: "swing"}
OTHER_PORTALS = {10, 11, 45, 46, 99, 101, 286, 287, 747, 749, 2902, 2926}

# Speed portals -> header speed index (kA4): 0=1x, 1=0.5x, 2=2x, 3=3x, 4=4x
SPEED_PORTALS = {200: 1, 201: 0, 202: 2, 203: 3, 1334: 4}
# Horizontal player speed in units per second for each speed index.
SPEED_UNITS_PER_SECOND = {0: 311.58, 1: 251.16, 2: 387.42, 3: 468.0, 4: 576.0}

START_POS = 31

# ---- triggers ----------------------------------------------------------------
COLOR_TRIGGER = 899
PULSE_TRIGGER = 1006

# ---- decoration pieces -----------------------------------------------------
FILL_SQUARE = 211        # plain 30x30 square, fully tintable
OUTLINE_LINE = 468       # 30 x 1.5 line through its center
OUTLINE_CORNER_DOT = 472 # 1.5 x 1.5 dot in the top-left corner of its 30x30 box
OUTLINE_SQUARE = 467     # 30x30 square outline
GLOW_EDGE = 503          # 30x20 gradient, bright on its bottom edge
GLOW_CORNER = 504        # 20x20 quarter-radial gradient, bright at its bottom-right corner
GLOW_SQUARE = 1011       # 30x30 gradient, bright on its bottom edge
PARTICLE_DOT = 1764      # 8x8 dot
PARTICLE_CROSS = 1765    # 8x8 "x"
PARTICLE_TRIANGLE = 1766 # 8x8 triangle
PARTICLE_SQUARE = 917    # 7.5x7.5 square
PARTICLE_SHAPES = {"dot": PARTICLE_DOT, "cross": PARTICLE_CROSS, "triangle": PARTICLE_TRIANGLE, "square": PARTICLE_SQUARE}
RING_ARC = 1835          # quarter ring arc, 30x30

# Built-in color channels.
BG, G1, LINE, OBJ, G2, MG, MG2 = 1000, 1001, 1002, 1004, 1009, 1013, 1014
