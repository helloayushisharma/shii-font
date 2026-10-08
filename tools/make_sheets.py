"""Generate the extra fill-in sheets (pages 2 & 3) and the writing guide.

    .venv/bin/python tools/make_sheets.py
"""
from pathlib import Path

from fontTools.ttLib import TTFont as FTFont
from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import layout as L

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sheets"

UNI = "/System/Library/Fonts/Helvetica.ttc"                         # has ₹
SYM = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"         # ① ✓ ✗
HAND = "/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf"
pdfmetrics.registerFont(TTFont("Uni", UNI, subfontIndex=0))
pdfmetrics.registerFont(TTFont("Sym", SYM))
pdfmetrics.registerFont(TTFont("Hand", HAND))

BORDER = HexColor("#4d4d4d")
GUIDE = HexColor("#c4c4c4")
INK = HexColor("#1f2a44")
GHOST = HexColor("#d9dde6")
OK = HexColor("#1f8a4c")
BAD = HexColor("#c0392b")
MUTED = HexColor("#6b6b6b")


def Y(y_top):
    """top-left origin → reportlab bottom-left origin."""
    return L.PAGE_H - y_top


# ---------------------------------------------------------------- sheets

def marker(c, x, y):
    band = L.MARKER / 7
    for k, col in enumerate((black, white, black, white)):
        inset = k * band
        size = L.MARKER - 2 * inset
        c.setFillColor(col)
        c.rect(x + inset, Y(y + inset + size), size, size, stroke=0, fill=1)


def page_id(c, n):
    for b in range(4):
        x = L.ID_BITS_X0 + b * (L.ID_BIT + L.ID_GAP)
        c.setStrokeColor(black)
        c.setLineWidth(0.6)
        c.setFillColor(black if (n >> (3 - b)) & 1 else white)
        c.rect(x, Y(L.ID_BITS_Y + L.ID_BIT), L.ID_BIT, L.ID_BIT, stroke=1, fill=1)


# Names for labels that are unreadable / ambiguous at 8pt.
HINTS = {
    "-": "hyphen", "–": "en dash", "—": "em dash", "_": "underscore",
    "/": "slash", "\\": "backslash", "|": "bar", "`": "backtick", "^": "caret",
    "~": "tilde", "°": "degree", "•": "bullet", "…": "ellipsis",
    "‘": "open quote", "’": "close quote", "“": "open dbl", "”": "close dbl",
    "«": "guillemet", "»": "guillemet", "¡": "inverted !", "¿": "inverted ?",
    "×": "times", "÷": "divide", "*": "asterisk",
    "´": "acute  é", "¨": "umlaut  ë", "¸": "cedilla  ç", "˚": "ring  å",
    "ˇ": "caron  č", "˘": "breve  ă", "¯": "macron  ā", "˙": "dot  ż",
}


def cell_frame(c, x, y, w, h, scale=1.0, label=None, variant=1, label_size=8):
    """One ruled cell. (x, y) is the top-left in top-origin page coords."""
    g = {k: v * scale for k, v in L.GUIDES.items()}
    c.setStrokeColor(GUIDE)
    c.setLineWidth(0.5 * max(1, scale * 0.7))
    for k in ("cap", "x", "base", "desc"):
        c.line(x, Y(y + g[k]), x + w, Y(y + g[k]))
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.75 * max(1, scale * 0.6))
    c.line(x, Y(y + L.HEADER * scale), x + w, Y(y + L.HEADER * scale))
    c.rect(x, Y(y + h), w, h, stroke=1, fill=0)
    if label is not None:
        c.setFillColor(black)
        c.setFont("Uni", label_size)
        c.drawString(x + 2.6 * scale, Y(y + L.HEADER * scale - 3.2 * scale), label)
        note = f"version {variant}" if variant > 1 else HINTS.get(label)
        if note:
            c.setFillColor(MUTED)
            c.setFont("Uni", label_size * 0.72)
            c.drawRightString(x + w - 2.6 * scale, Y(y + L.HEADER * scale - 3.2 * scale), note)


def sheet(c, n):
    for x, y in L.MARKERS.values():
        marker(c, x, y)
    title, sub = "shii font", f"   sheet {n} of 3  ·  {L.PAGE_TITLES[n]}"
    tw = pdfmetrics.stringWidth(title, "Uni", 14) + pdfmetrics.stringWidth(sub, "Uni", 9)
    tx = (L.PAGE_W - tw) / 2
    c.setFillColor(black)
    c.setFont("Uni", 14)
    c.drawString(tx, Y(51), title)
    c.setFillColor(MUTED)
    c.setFont("Uni", 9)
    c.drawString(tx + pdfmetrics.stringWidth(title, "Uni", 14), Y(51), sub)
    for i, entry in enumerate(L.PAGES[n]):
        x, y, w, h = L.cell_rect(i)
        if entry is None:
            continue
        ch, var = entry
        cell_frame(c, x, y, w, h, label=ch, variant=var)
    page_id(c, n)
    c.setFillColor(MUTED)
    c.setFont("Uni", 8)
    c.drawString(70, Y(672), "Include all four corner markers,")
    c.drawString(70, Y(682), "untrimmed, in your scan or photo.")
    c.drawRightString(466, Y(677), f"sheet {n} / 3")


# ---------------------------------------------------------------- guide

_hand = FTFont(HAND)
_gs = _hand.getGlyphSet()
_cmap = _hand.getBestCmap()
_glyf = _hand["glyf"]


def bounds(ch):
    g = _glyf[_cmap[ord(ch)]]
    g.recalcBounds(_glyf)
    return g.xMin, g.yMin, g.xMax, g.yMax


CAP_U = bounds("H")[3]
X_U = bounds("x")[3]


def hand_glyph(c, ch, cx, base_y, scale, kind, color=INK):
    """Draw ch centred on cx, sitting on base_y (top-origin), sized to the guides."""
    target = (L.GUIDES["base"] - L.GUIDES["cap"]) if kind == "cap" else (L.GUIDES["base"] - L.GUIDES["x"])
    units = CAP_U if kind == "cap" else X_U
    size = target * scale * 1000 / units
    x0, _, x1, _ = bounds(ch)
    gx = cx - (x0 + x1) / 2 * size / 1000
    c.setFillColor(color)
    c.setFont("Hand", size)
    c.drawString(gx, Y(base_y), ch)


def example_row(c, x, y, scale, title, note, items, gap=8):
    """items: list of (glyphs, kind, ghost, mark, base_shift) per cell."""
    w, h = L.CELL_W * scale, L.CELL_H * scale
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x, Y(y - 16), title)
    c.setFont("Helvetica", 8.6)
    c.setFillColor(MUTED)
    c.drawString(x, Y(y - 5), note)
    for k, it in enumerate(items):
        glyph, kind = it[0], it[1]
        ghost = it[2] if len(it) > 2 else None
        mark = it[3] if len(it) > 3 else None
        shift = it[4] if len(it) > 4 else 0
        size_mul = it[5] if len(it) > 5 else 1.0
        cx0 = x + k * (w + gap)
        cell_frame(c, cx0, y, w, h, scale=scale, label=glyph if mark is None else "",
                   label_size=8 * scale * 0.8)
        base = y + L.GUIDES["base"] * scale
        c.saveState()
        p = c.beginPath()
        p.rect(cx0, Y(y + h), w, h)
        c.clipPath(p, stroke=0, fill=0)
        if ghost:
            hand_glyph(c, ghost, cx0 + w / 2, base, scale, "x", color=GHOST)
        hand_glyph(c, glyph, cx0 + w / 2, base + shift * scale, scale * size_mul, kind)
        c.restoreState()
        if mark:
            c.setFillColor(OK if mark == "ok" else BAD)
            c.setFont("Sym", 9 * scale * 0.8)
            c.drawString(cx0 + 2.6 * scale, Y(y + L.HEADER * scale - 3.2 * scale),
                         "✓ right" if mark == "ok" else "✗ wrong")
    return y + h


def guide(c):
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(40, Y(56), "How to fill in the sheets")
    c.setFont("Helvetica", 9.5)
    c.setFillColor(MUTED)
    c.drawString(40, Y(72), "Every cell has the same four guide lines. Where a letter touches them decides how it sits in the font.")

    # --- big annotated cell
    s = 1.8
    bx, by = 40, 92
    w, h = L.CELL_W * s * 2.5, L.CELL_H * s
    cell_frame(c, bx, by, w, h, scale=s, label="H  h  x  g", label_size=9)
    base = by + L.GUIDES["base"] * s
    for ch, kind, dx in (("H", "cap", 0.17), ("h", "x", 0.41), ("x", "x", 0.635), ("g", "x", 0.86)):
        hand_glyph(c, ch, bx + w * dx, base, s, kind)
    lx = bx + w + 14
    notes = [
        ("cap", "①  capital line", "tops of CAPITALS, numbers and tall letters b d f h k l"),
        ("x", "②  x-height line", "tops of small letters a c e m n o r s u v w x z"),
        ("base", "③  baseline", "EVERYTHING sits on this line — the key one"),
        ("desc", "④  tail line", "tails of g j p q y hang down to here"),
    ]
    for k, name, desc in notes:
        yy = by + L.GUIDES[k] * s
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.setDash(2, 2)
        c.line(bx + w + 2, Y(yy), lx + 4, Y(yy))
        c.setDash()
        c.setFillColor(black)
        c.setFont("Sym", 9.5)
        c.drawString(lx + 8, Y(yy - 3.2), name)
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawString(lx + 8, Y(yy + 7.5), desc)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(lx + 8, Y(by + L.HEADER * s - 5), "label strip — never write in here")

    # --- example rows
    s = 1.0
    x0 = 40
    y = by + h + 40
    rows = [
        ("CAPITALS", "Sit on ③, top touches ①. Q's tail may dip below ③.",
         [("A", "cap"), ("H", "cap"), ("M", "cap"), ("Q", "cap"), ("R", "cap"), ("J", "cap")]),
        ("small letters", "Sit on ③, top touches ②. Round letters (o, e) can poke just past the lines.",
         [("a", "x"), ("e", "x"), ("m", "x"), ("o", "x"), ("r", "x"), ("s", "x")]),
        ("tall small letters & tails", "Stems rise to ①, tails drop to ④. t is a bit shorter than the others.",
         [("b", "x"), ("d", "x"), ("k", "x"), ("t", "x"), ("g", "x"), ("y", "x")]),
        ("numbers & punctuation", "Numbers = capital height. Comma dips under ③, apostrophe hangs from ①.",
         [("4", "cap"), ("7", "cap"), (",", "cap"), ("'", "cap"), ("(", "cap"), ("-", "x")]),
    ]
    for title, note, items in rows:
        y = example_row(c, x0, y, s, title, note, items) + 30

    # accents + do/don't
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(x0, Y(y - 16), "accents (sheet 2)  ·  common mistakes")
    c.setFont("Helvetica", 8.6)
    c.setFillColor(MUTED)
    c.drawString(x0, Y(y - 5), "Write ONLY the accent, where it would sit over a small letter (grey e = imaginary). "
                 "Then: wrong vs right.")
    items = [
        ("´", "x", "e"), ("¸", "x", "c"),
        ("a", "x", None, "bad", -7),          # floating above baseline
        ("H", "cap", None, "bad", 6, 1.55),   # too big, crashes into border/label
        ("a", "x", None, "bad", 0, 0.55),     # too small
        ("a", "x", None, "ok"),
    ]
    example_row(c, x0, y, s, "", "", items)
    lab_y = y + L.CELL_H * s + 11
    c.setFont("Helvetica", 7.6)
    c.setFillColor(MUTED)
    w = L.CELL_W * s + 8
    for k, t in enumerate(["acute  (é)", "cedilla  (ç)", "floating", "too big", "too small", "on the line"]):
        c.drawCentredString(x0 + k * w + L.CELL_W * s / 2, Y(lab_y), t)

    # tips (right-hand column, beside rows)
    tx = x0 + 6 * (L.CELL_W + 8) + 26
    ty = by + L.CELL_H * 1.8 + 58
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(tx, Y(ty), "Tips")
    tips = [
        "Same pen for every sheet —",
        "dark gel or felt-tip, not",
        "ballpoint.",
        "",
        "Write naturally, at your",
        "normal speed. Neat-but-you,",
        "not neat-but-stiff.",
        "",
        "Keep sizes consistent",
        "across all 3 sheets.",
        "",
        "Never touch the cell",
        "border — it gets clipped.",
        "Leave the strip under",
        "line ④ empty too.",
        "",
        "Versions 2 & 3 (sheet 3)",
        "should differ a little,",
        "like they do when you",
        "write a sentence. Don't",
        "force them different.",
        "",
        "Skip a cell? Leave it",
        "blank; it's fine.",
        "",
        "Scan at 300 dpi, or shoot",
        "flat in daylight with all",
        "4 corner markers visible.",
    ]
    c.setFont("Helvetica", 8.2)
    c.setFillColor(HexColor("#333333"))
    for i, t in enumerate(tips):
        c.drawString(tx, Y(ty + 16 + i * 11), t)


def main():
    OUT.mkdir(exist_ok=True)
    pdf = OUT / "shii_sheets_1-3.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(L.PAGE_W, L.PAGE_H))
    c.setTitle("shii font — sheets 1-3")
    for n in (1, 2, 3):
        sheet(c, n)
        c.showPage()
    c.save()

    c = canvas.Canvas(str(OUT / "writing_guide.pdf"), pagesize=(L.PAGE_W, L.PAGE_H))
    c.setTitle("shii font — writing guide")
    guide(c)
    c.showPage()
    c.save()

    # Procreate canvases: flat white PNGs at a fixed dpi (the reader maps
    # pixels back to layout points with the same dpi, read from the size).
    import pymupdf
    for dpi in (600, 400):
        d = OUT / "procreate" / f"{dpi}dpi"
        d.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(pymupdf.open(pdf)):
            page.get_pixmap(dpi=dpi, alpha=False).save(d / f"shii_sheet{i + 1}_{dpi}dpi.png")
    print("wrote", pdf.name, "writing_guide.pdf", "procreate/{600,400}dpi/*.png")


if __name__ == "__main__":
    main()
