"""Write variants_review.html — every version of every letter, repeated and in words,
so Ayushi can pick which versions the font rotates through.

    .venv/bin/python tools/make_variants_review.py
"""
import json
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).parent))
import build_font as B  # noqa: E402

ROOT = B.ROOT
OUT = ROOT / "build" / "review"

# a build that keeps every drawing, so dropped versions can still be shown
tune = B.load_tuning()
current = tune.get("variants", {})
B.main(sorted((ROOT / "input").glob("*.psd"))[-1], {**tune, "variants": {}}, OUT)

f = TTFont(OUT / "Shii-Regular.otf")
gs, hmtx, cmap = f.getGlyphSet(), f["hmtx"], f.getBestCmap()
glyphs = {}
for name in f.getGlyphOrder():
    pen = SVGPathPen(gs)
    gs[name].draw(pen)
    glyphs[name] = {"d": pen.getCommands(), "adv": hmtx[name][0]}

letters = {}
for ch in "abcdefghijklmnopqrstuvwxyzTASIMCBPHWND":
    base = cmap[ord(ch)]
    letters[ch] = 1 + sum(f"{base}.alt{v}" in glyphs for v in (2, 3))

data = {
    "glyphs": glyphs, "cmap": {chr(u): n for u, n in cmap.items()},
    "ascent": f["hhea"].ascent, "descent": f["hhea"].descent, "space": tune["space"],
    "letters": letters, "current": current,
    "gaps": json.loads((OUT / "double_gaps.json").read_text()) if (OUT / "double_gaps.json").exists() else {},
}
html = (Path(__file__).parent / "variants_review_template.html").read_text()
(ROOT / "variants_review.html").write_text(html.replace("__DATA__", json.dumps(data)))
print("wrote variants_review.html")
