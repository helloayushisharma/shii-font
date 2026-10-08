"""Shared sheet geometry + page contents.

All measurements are in PDF points with a TOP-LEFT origin (y grows downward),
measured from the Calligraphr A4 template so every sheet shares one reader.
"""

PAGE_W, PAGE_H = 595.28, 841.89

# Concentric registration markers: 7 equal bands B W B W B W B (white centre).
MARKER = 24.0
MARKERS = {  # top-left corner of each marker
    "tl": (42.48, 33.84),
    "tr": (471.84, 33.84),
    "bl": (42.48, 661.68),
    "br": (471.84, 661.68),
}

GRID_X0, GRID_Y0 = 42.6, 61.08
COLS, ROWS = 8, 8
CELL_W, CELL_H = 56.64, 73.68

HEADER = 11.88          # label strip at the top of each cell
GUIDES = {              # offsets from cell top
    "cap": 21.24,       # L1  capitals, digits, ascenders (b d h k l)
    "x": 33.48,         # L2  x-height: top of a c e m n o ...
    "base": 53.16,      # L3  baseline
    "desc": 64.68,      # L4  descenders (g j p q y)
}

# 4-bit page id, drawn as small squares bottom-centre (page 1 = blank = 0).
ID_BITS_X0, ID_BITS_Y, ID_BIT, ID_GAP = 263.0, 668.0, 9.0, 9.0


def cell_rect(i):
    """(x, y, w, h) of cell i, row-major."""
    r, c = divmod(i, COLS)
    return GRID_X0 + c * CELL_W, GRID_Y0 + r * CELL_H, CELL_W, CELL_H


# Each entry: (glyph, variant). variant 1 = default form.
# None = cell unused (page 1's QR block).
_P1_TOP = list("!\"',.:;?ABCD")
PAGE1 = []
for i, ch in enumerate(_P1_TOP):
    PAGE1.append((ch, 1))
    if i in (5, 11):          # cols 7-8 of rows 1-2 are the QR code
        PAGE1 += [None, None]
PAGE1 += [(c, 1) for c in "EFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"]

_P2 = (
    list("0123456789")
    + list("-–—_()[]{}/\\|&@#%*+=<>~^`$€£₹°©®™•…‘’“”«»¡¿×÷±")
    # spacing accents → combined with base letters later (é è ë ê ñ ç å č ...)
    + list("´¨¸˚ˇ˘¯˙")
)
PAGE2 = [(c, 1) for c in _P2]

PAGE3 = (
    [(c, 2) for c in "abcdefghijklmnopqrstuvwxyz"]
    + [(c, 3) for c in "abcdefghijklmnopqrstuvwxyz"]
    + [(c, 2) for c in "TASIMCBPHWND"]
)

PAGES = {1: PAGE1, 2: PAGE2, 3: PAGE3}
PAGE_TITLES = {
    1: "letters & basic punctuation",
    2: "numbers, punctuation & accents",
    3: "alternates — 2nd & 3rd versions",
}

assert len(PAGE1) == 64 and len(PAGE2) == 64 and len(PAGE3) == 64, (
    len(PAGE1), len(PAGE2), len(PAGE3))
