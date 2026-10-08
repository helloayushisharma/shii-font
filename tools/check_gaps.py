"""Closest outline-to-outline gap (font units) for letter pairs in the built font.

    .venv/bin/python tools/check_gaps.py [pair ...]
"""
import sys
import numpy as np, cv2, uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.pens.basePen import BasePen

FONT = "build/Shii-Regular.otf"
f = TTFont(FONT); gs = f.getGlyphSet()
hbf = hb.Font(hb.Face(hb.Blob.from_file_path(FONT)))
K = 0.25


class Poly(BasePen):
    def __init__(s, gs): super().__init__(gs); s.polys, s.cur = [], []
    def _moveTo(s, p): s.cur = [p]
    def _lineTo(s, p): s.cur.append(p)
    def _curveToOne(s, a, b, c):
        p0 = np.array(s.cur[-1]); a, b, c = map(np.array, (a, b, c))
        for t in np.linspace(0, 1, 12)[1:]:
            mt = 1 - t; s.cur.append(tuple(mt**3 * p0 + 3 * mt * mt * t * a + 3 * mt * t * t * b + t**3 * c))
    def _closePath(s): s.polys.append(s.cur); s.cur = []
    _endPath = _closePath


def mask(name, dx):
    pen = Poly(gs); gs[name].draw(pen)
    img = np.zeros((int(1500 * K), int(3200 * K)), np.uint8)
    cv2.fillPoly(img, [np.array([[(x + dx) * K, (1100 - y) * K] for x, y in p], np.int32) for p in pen.polys], 255)
    return img > 0


def min_gap(text):
    b = hb.Buffer(); b.add_str(text); b.guess_segment_properties(); hb.shape(hbf, b, {"calt": True, "kern": True})
    names = [hbf.glyph_to_string(i.codepoint) for i in b.glyph_infos]; advs = [p.x_advance for p in b.glyph_positions]
    x, worst = 200, 1e9
    for i in range(len(names) - 1):
        a, c = mask(names[i], x), mask(names[i + 1], x + advs[i])
        for r in np.where(a.any(1) & c.any(1))[0]:
            worst = min(worst, (np.where(c[r])[0].min() - np.where(a[r])[0].max()) / K)
        x += advs[i]
    return round(worst)


if __name__ == "__main__":
    pairs = sys.argv[1:] or [c * 4 for c in "abcdefghijklmnopqrstuvwxyzTASIMCBPHWND"]
    print("  ".join(f"{p}:{min_gap(p)}" for p in pairs))
