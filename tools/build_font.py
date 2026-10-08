"""PSD (Procreate export) → Shii-Regular.otf

    .venv/bin/python tools/build_font.py [input/whatever.psd]

The PSD holds pairs of layers: a template sheet with an ink layer above it.
Tuning (spacing, kerning, metrics) is read from tuning.json at the project
root, which the tuning tool exports.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pathops
import potrace
from fontTools.agl import UV2AGL
from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
from psd_tools import PSDImage

import layout as L

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WORK = ROOT / "work"

FAMILY = "Shii"
VERSION = "1.000"
DESIGNER = "Ayushi Sharma"
COPYRIGHT = f"Copyright 2026 {DESIGNER}"
UPM = 1000
CAP = 700                                         # font units for line ①
U = CAP / (L.GUIDES["base"] - L.GUIDES["cap"])    # font units per pt
XH = round((L.GUIDES["base"] - L.GUIDES["x"]) * U)
UP = 4                                            # supersampling before tracing

DEFAULTS = {
    "sidebearing": 45,       # default left/right sidebearing, units
    "space": 260,
    "tracking": 0,           # added to every advance
    "lineGap": 200,
    "glyphs": {},            # name -> {"lsb": n, "rsb": n}
    "kerning": {},           # "a v" -> value
    "variants": {},          # "g": [2, 3] -> which drawings to use, first = default
}


# ------------------------------------------------------------ PSD reading

def layer_rgba(layer, w, h):
    im = np.zeros((h, w, 4), np.uint8)
    pil = layer.topil()
    if pil is None:
        return im
    a = np.array(pil.convert("RGBA"))
    x0, y0 = layer.offset
    im[y0:y0 + a.shape[0], x0:x0 + a.shape[1]] = a
    return im


def is_template(rgba):
    """Templates are mostly white/grey paper; ink layers are sparse black."""
    alpha = rgba[..., 3] > 0
    if alpha.mean() > 0.5:
        return True
    grey = alpha & (rgba[..., :3].mean(-1) > 60)
    return grey.sum() > 0.25 * alpha.sum()


def on_white(rgba):
    a = rgba[..., 3:4] / 255.0
    return (rgba[..., :3].mean(-1, keepdims=True) * a + 255 * (1 - a))[..., 0]


def register(grey):
    """Affine pt→px from the four corner markers."""
    # Procreate may crop/scale the page on import, so don't assume a scale:
    # the markers are the square rings (outer band ≈ 49% filled) nearest
    # each canvas corner.
    h, w = grey.shape
    dark = (grey < 110).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(dark)
    rings = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if bw > 0.02 * w and abs(bw - bh) < 0.1 * bw and 0.3 < area / (bw * bh) < 0.7:
            rings.append((x + bw / 2, y + bh / 2))
    corners = {"tl": (0, 0), "tr": (w, 0), "bl": (0, h), "br": (w, h)}
    src, dst = [], []
    for key, (mx, my) in L.MARKERS.items():
        if not rings:
            raise SystemExit("no corner markers found on template layer")
        cx, cy = corners[key]
        best = min(rings, key=lambda p: np.hypot(p[0] - cx, p[1] - cy))
        src.append((mx + L.MARKER / 2, my + L.MARKER / 2))
        dst.append(best)
    A, _ = cv2.estimateAffine2D(np.float32(src), np.float32(dst))
    return A


def page_number(grey, A):
    bits = 0
    for b in range(4):
        x = L.ID_BITS_X0 + b * (L.ID_BIT + L.ID_GAP) + L.ID_BIT / 2
        px, py = A @ (x, L.ID_BITS_Y + L.ID_BIT / 2, 1)
        r = max(2, int(A[0, 0] * L.ID_BIT * 0.25))
        patch = grey[int(py) - r:int(py) + r, int(px) - r:int(px) + r]
        bits = (bits << 1) | int(patch.mean() < 128)
    return bits or 1          # Calligraphr's own sheet has no id → page 1


def read_psd(path):
    psd = PSDImage.open(path)
    w, h = psd.width, psd.height
    layers = [layer_rgba(l, w, h) for l in psd if l.kind == "pixel" and l.name != "Background"]
    pages, current = {}, None
    for rgba in layers:                     # bottom → top
        if is_template(rgba):
            grey = on_white(rgba)
            A = register(grey)
            current = page_number(grey, A)
            pages[current] = {"A": A, "ink": np.zeros((h, w), np.float32)}
        elif current is not None:
            pages[current]["ink"] = np.maximum(pages[current]["ink"], rgba[..., 3] / 255.0)
    return pages


# ------------------------------------------------------------ glyph extraction

def clean(alpha, A):
    """Blur away brush grain, then binarise."""
    s = A[0, 0]                            # px per pt
    sig = 0.35 * s
    soft = cv2.GaussianBlur(alpha, (0, 0), sig)
    return soft, soft > 0.4


def cells_for_page(n, page):
    A = page["A"]
    soft, mask = clean(page["ink"], A)
    cnt, lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    Ai = cv2.invertAffineTransform(A)
    s = A[0, 0]
    min_area = (0.6 * s) ** 2              # specks smaller than ~0.6pt square
    owner = {}
    for i in range(1, cnt):
        if st[i, 4] < min_area:
            continue
        cx, cy = Ai @ (*cen[i], 1)
        c = int((cx - L.GRID_X0) // L.CELL_W)
        r = int((cy - L.GRID_Y0) // L.CELL_H)
        if 0 <= c < L.COLS and 0 <= r < L.ROWS:
            owner.setdefault(r * L.COLS + c, []).append(i)
    out = {}
    for idx, comps in owner.items():
        entry = L.PAGES[n][idx]
        if entry is None:
            continue
        m = np.isin(lab, comps)
        ys, xs = np.nonzero(m)
        pad = int(2 * s)
        y0, y1 = max(0, ys.min() - pad), ys.max() + pad + 1
        x0, x1 = max(0, xs.min() - pad), xs.max() + pad + 1
        keep = cv2.dilate(m[y0:y1, x0:x1].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        crop = soft[y0:y1, x0:x1] * keep
        out[entry] = (crop, x0, y0, idx)
    return out


def trace(crop, x0, y0, A, idx, k=1.0, dy=0.0, grow=0.0):
    """Trace one glyph into font units (origin = cell baseline-left).

    k / dy scale and shift the result (y' = y*k + dy); grow (font units)
    fattens (+) or thins (-) the stroke first, so a glyph scaled by k can
    keep the same stroke weight as the letters.
    Returns (pen, stroke_width_in_font_units).
    """
    big = cv2.resize(crop, None, fx=UP, fy=UP, interpolation=cv2.INTER_CUBIC)
    big = cv2.GaussianBlur(big, (0, 0), UP * 0.6)
    ink = big > 0.45
    u_per_px = U / (A[0, 0] * UP)              # font units per supersampled px

    dist = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 5)
    ridge = (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8))) & (dist > 2)
    sw = 2 * float(np.median(dist[ridge])) * u_per_px if ridge.any() else 0.0

    r = int(round(abs(grow) / u_per_px))
    if r:
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
        op = cv2.dilate if grow > 0 else cv2.erode
        ink = op(ink.astype(np.uint8), ker) > 0

    bm = potrace.Bitmap(~ink)
    paths = bm.trace(turdsize=int(UP * UP * 3), alphamax=1.0, opticurve=True, opttolerance=0.35)

    Ai = cv2.invertAffineTransform(A)
    cx, cy, _, _ = L.cell_rect(idx)
    base = cy + L.GUIDES["base"]

    def f(p):
        px, py = x0 + p.x / UP, y0 + p.y / UP
        xp, yp = Ai @ (px, py, 1)
        return ((xp - cx) * U * k, (base - yp) * U * k + dy)

    pen = RecordingPen()
    for curve in paths:
        pen.moveTo(f(curve.start_point))
        for seg in curve.segments:
            if seg.is_corner:
                pen.lineTo(f(seg.c))
                pen.lineTo(f(seg.end_point))
            else:
                pen.curveTo(f(seg.c1), f(seg.c2), f(seg.end_point))
        pen.closePath()
    return pen, sw


def simplify(rec):
    p = pathops.Path()
    rec.replay(p.getPen())
    p.simplify(fix_winding=True, keep_starting_points=False)
    out = RecordingPen()
    p.draw(out)
    return out


def bounds(rec):
    bp = BoundsPen(None)
    rec.replay(bp)
    return bp.bounds


def moved(rec, dx=0, dy=0, sx=1, sy=1):
    out = RecordingPen()
    rec.replay(TransformPen(out, (sx, 0, 0, sy, dx, dy)))
    return out


def merge(*recs):
    out = RecordingPen()
    for r in recs:
        out.value += r.value
    return simplify(out)


# ------------------------------------------------------------ naming

def gname(ch, var=1):
    base = UV2AGL.get(ord(ch), f"uni{ord(ch):04X}")
    return base if var == 1 else f"{base}.alt{var}"


# ------------------------------------------------------------ accents

ACCENTS = {   # mark char → letters it builds
    "´": "áéíóúýÁÉÍÓÚÝćńśźĆŃŚŹ",
    "`": "àèìòùÀÈÌÒÙ",
    "¨": "äëïöüÿÄËÏÖÜ",
    "˚": "åůÅŮ",
    "ˇ": "čšžřěňČŠŽŘĚŇ",
    "˘": "ăğĂĞ",
    "¯": "āēīōūĀĒĪŌŪ",
    "˙": "żėŻĖ",
    "^": "âêîôûÂÊÎÔÛ",
    "~": "ãñõÃÑÕ",
    "¸": "çşÇŞ",
}


def strip_dot(rec):
    """i → ı : drop contours sitting entirely above the x-height."""
    p = pathops.Path()
    rec.replay(p.getPen())
    keep = RecordingPen()
    for contour in p.contours:
        b = contour.bounds
        if b[1] < XH * 0.85:
            contour.draw(keep)
    return keep


def build_accented(glyphs):
    import unicodedata
    made = {}
    # Normalise the oversized ASCII ^ and ~ to the size of the acute mark.
    ref = bounds(glyphs[gname("´")]) if gname("´") in glyphs else None
    for mark, letters in ACCENTS.items():
        mn = gname(mark)
        if mn not in glyphs:
            continue
        m = glyphs[mn]
        if mark == "`" and ref:          # the sheet's backtick isn't a grave shape
            m = moved(glyphs[gname("´")], sx=-1)
        mb = bounds(m)
        if mark in "^~" and ref:
            k = (ref[2] - ref[0]) * 1.25 / (mb[2] - mb[0])
            m = moved(m, sx=k, sy=k)
            mb = bounds(m)
            m = moved(m, dy=ref[1] - mb[1])    # sit at the acute's height
            mb = bounds(m)
        for ch in letters:
            base_ch = unicodedata.normalize("NFD", ch)[0]
            bn = gname(base_ch)
            if bn not in glyphs:
                continue
            b = glyphs[bn]
            if base_ch in "ij" and mark != "¸":
                b = strip_dot(b)
            bb = bounds(b)
            dx = (bb[0] + bb[2]) / 2 - (mb[0] + mb[2]) / 2
            dy = 0
            if mark != "¸":
                top = bb[3] if base_ch.isupper() else XH
                gap = mb[1] - XH                 # as written on the sheet
                dy = (top + max(gap, 40)) - mb[1]
            made[gname(ch)] = (ord(ch), merge(b, moved(m, dx, dy)), bn)
    return made



# ------------------------------------------------------------ normalisation
# Glyphs keep their handwritten shape but are snapped to standard positions.
# C / X are the measured cap- and x-height of the letters.

FLAT_BOTTOMS = "HITEFLNMKlnmhrikuxz"
CAP_TOPS = "HITEFLNK"
X_TOPS = "xznmruvw"

# scale into a vertical box (stroke weight preserved).  together=True keeps
# a set (e.g. all digits) at one common size.
BOXES = [
    ("0123456789", lambda C, X: (0, C), True),
    ("!?#%&€£₹©®", lambda C, X: (0, C), False),
    ("@", lambda C, X: (-0.08 * C, 0.95 * C), False),
    ("$", lambda C, X: (-0.1 * C, 1.1 * C), False),
    ("()[]{}", lambda C, X: (-0.28 * C, 1.06 * C), True),
    ("/\\|", lambda C, X: (-0.2 * C, 1.06 * C), False),
    ("¡¿", lambda C, X: (X - C, X), False),
    ("™", lambda C, X: (0.55 * C, C), False),
    ("+=×÷±<>~", lambda C, X: (0.18 * C, 0.76 * C), True),   # sized as a set, centred below
    ("*", lambda C, X: (0.55 * C, C), False),
    ("^", lambda C, X: (0.6 * C, C), False),
    ("°", lambda C, X: (0.62 * C, C), False),
]

SNAP_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
SNAP_SKIP = "fjQ"                 # tails/descenders make the bottom meaningless
DESC_TOP = "gpqy"                 # align these by their x-height top instead
ROUND_BOTTOM = "abcdeosuCGJOSU035689"
OVERSHOOT = 8

# move only.  kind: bottom / top / center → target y
ANCHORS = [
    (".…:", "bottom", lambda C, X, b: -5),
    (",", "top", lambda C, X, b: b["period"][3]),
    (";", "top", lambda C, X, b: b["colon"][3]),
    ("'\"‘’“”`", "top", lambda C, X, b: C + 20),
    ("*°^", "top", lambda C, X, b: C),
    ("-–—•", "center", lambda C, X, b: 0.5 * X + 10),
    ("+=×÷±<>~", "center", lambda C, X, b: 0.47 * C),
    ("«»", "center", lambda C, X, b: 0.5 * X),
    ("_", "top", lambda C, X, b: -60),
]


def normalise(glyphs, sources, strokes):
    med = lambda v: float(np.median(v))
    have = lambda chars: [gname(c) for c in chars if gname(c) in glyphs]
    B = {n: bounds(r) for n, r in glyphs.items()}

    shift = -med([B[n][1] for n in have(FLAT_BOTTOMS)])
    for n in glyphs:
        glyphs[n] = moved(glyphs[n], dy=shift)
        b = B[n]
        B[n] = (b[0], b[1] + shift, b[2], b[3] + shift)
    C = med([B[n][3] for n in have(CAP_TOPS)])
    X = med([B[n][3] for n in have(X_TOPS)])
    sw = med([strokes[n] for n in glyphs if n.split(".")[0].isalpha() and len(n.split(".")[0]) == 1])
    print(f"  baseline +{shift:.0f}  cap {C:.0f}  x-height {X:.0f}  stroke {sw:.0f}")

    for chars, box, together in BOXES:
        names = have(chars)
        if not names:
            continue
        lo, hi = box(C, X)
        groups = [names] if together else [[n] for n in names]
        for grp in groups:
            y0, y1 = med([B[n][1] for n in grp]), med([B[n][3] for n in grp])
            k = (hi - lo) / (y1 - y0)
            for n in grp:
                grow = max(-0.4, min(0.4, (sw / k - strokes[n]) / 2 / strokes[n])) * strokes[n]
                rec, _ = trace(*sources[n], k=k, dy=lo + (shift - y0) * k, grow=grow)
                glyphs[n] = simplify(rec)
                B[n] = bounds(glyphs[n])

    # Every drawing (each version of each letter/digit) sits on the baseline
    # on its own — versions were written in separate cells and bounce.
    for c in SNAP_CHARS:
        if c in SNAP_SKIP:
            continue
        for var in (1, 2, 3):
            n = gname(c, var)
            if n not in glyphs:
                continue
            b = B[n]
            if c in DESC_TOP:
                d = X + OVERSHOOT - b[3]
            else:
                d = (-OVERSHOOT if c in ROUND_BOTTOM else 0) - b[1]
            glyphs[n] = moved(glyphs[n], dy=d)
            B[n] = (b[0], b[1] + d, b[2], b[3] + d)
    C = med([B[n][3] for n in have(CAP_TOPS)])
    X = med([B[n][3] for n in have(X_TOPS)])
    print(f"  after snapping: cap {C:.0f}  x-height {X:.0f}")

    for chars, kind, target in ANCHORS:
        for n in have(chars):
            b = B[n]
            t = target(C, X, B)
            cur = {"bottom": b[1], "top": b[3], "center": (b[1] + b[3]) / 2}[kind]
            glyphs[n] = moved(glyphs[n], dy=t - cur)
            B[n] = (b[0], b[1] + t - cur, b[2], b[3] + t - cur)
    return round(C), round(X)

# ------------------------------------------------------------ build

def load_tuning():
    t = dict(DEFAULTS)
    f = ROOT / "tuning.json"
    if f.exists():
        t.update(json.loads(f.read_text()))
    return t


def base_of(name, accent_base):
    """a.alt2 → a ; eacute → e.  Variants and accented letters share the
    base letter's spacing and kerning unless they have their own."""
    name = name.split(".alt")[0]
    return accent_base.get(name, name)


def main(psd_path, tune=None, outdir=None):
    """tune / outdir let other tools build a variant (e.g. with every letter version kept)."""
    tune = tune or load_tuning()
    out_dir = Path(outdir) if outdir else BUILD
    pages = read_psd(psd_path)
    print("pages found:", sorted(pages))

    global XH
    glyphs, cmap, order, sources, strokes = {}, {}, [], {}, {}
    for n in sorted(pages):
        cells = cells_for_page(n, pages[n])
        missing = [e[0] + ("" if e[1] == 1 else f".{e[1]}") for e in L.PAGES[n] if e and e not in cells]
        if missing:
            print(f"  sheet {n}: empty cells → {' '.join(missing)}")
        for (ch, var), (crop, x0, y0, idx) in sorted(cells.items(), key=lambda kv: kv[1][3]):
            name = gname(ch, var)
            sources[name] = (crop, x0, y0, pages[n]["A"], idx)
            rec, strokes[name] = trace(*sources[name])
            glyphs[name] = simplify(rec)
            if var == 1:
                cmap[ord(ch)] = name
            order.append(name)

    cap_h, XH = normalise(glyphs, sources, strokes)
    if "quoteright" in glyphs and "quotesingle" in glyphs:
        # the straight ' is mostly typed as an apostrophe (it's) → use the ’ shape
        glyphs["quotesingle"] = moved(glyphs["quoteright"])

    # pick which drawings each letter uses (e.g. drop a version with a
    # different structure); the first listed becomes the default form
    for ch, keep in tune["variants"].items():
        picked = [glyphs[gname(ch, v)] for v in keep if gname(ch, v) in glyphs]
        for v in (1, 2, 3):
            glyphs.pop(gname(ch, v), None)
        for i, rec in enumerate(picked):
            glyphs[gname(ch, i + 1)] = rec
            if gname(ch, i + 1) not in order:
                order.append(gname(ch, i + 1))

    accent_base = {}
    for name, (uni, rec, bn) in build_accented(glyphs).items():
        glyphs[name] = rec
        cmap[uni] = name
        order.append(name)
        accent_base[name] = bn
    if "i" in glyphs:
        glyphs["dotlessi"] = strip_dot(glyphs["i"])
        cmap[0x131] = "dotlessi"
        order.append("dotlessi")
        accent_base["dotlessi"] = "i"

    # spacing: place each outline at its lsb, advance = width + lsb + rsb
    sb = tune["sidebearing"]
    charstrings, metrics, ink, dys = {}, {}, {}, {}
    ascii_names = {cmap[u] for u in range(0x21, 0x7F) if u in cmap}
    line_min, line_max, win_min, win_max = 0, cap_h, 0, cap_h
    for name, rec in glyphs.items():
        b = bounds(rec)
        if b is None:
            continue
        g = {**tune["glyphs"].get(base_of(name, accent_base), {}), **tune["glyphs"].get(name, {})}
        lsb, rsb = g.get("lsb", sb), g.get("rsb", sb)
        ink[name] = round(b[2] - b[0])
        own = tune["glyphs"].get(name, {})
        dys[name] = own.get("dy", tune["glyphs"].get(accent_base.get(name, ""), {}).get("dy", 0))
        rec = moved(rec, dx=lsb - b[0], dy=dys[name])
        b = bounds(rec)
        adv = round(b[2] - b[0] + lsb + rsb + tune["tracking"])
        pen = T2CharStringPen(adv, None)
        rec.replay(pen)
        charstrings[name] = pen.getCharString()
        metrics[name] = (adv, round(lsb))
        win_min, win_max = min(win_min, b[1]), max(win_max, b[3])
        if name in ascii_names:
            line_min, line_max = min(line_min, b[1]), max(line_max, b[3])
        glyphs[name] = rec

    for name, uni, w in ((".notdef", None, 500), ("space", 0x20, tune["space"]), ("uni00A0", 0xA0, tune["space"])):
        pen = T2CharStringPen(w, None)
        if name == ".notdef":                    # the standard empty box
            for (x0, y0, x1, y1), ccw in (((50, 0, 450, cap_h), True), ((110, 60, 390, cap_h - 60), False)):
                pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                pts = pts if ccw else pts[::-1]
                pen.moveTo(pts[0]); [pen.lineTo(q) for q in pts[1:]]; pen.closePath()
        charstrings[name] = pen.getCharString()
        metrics[name] = (w + tune["tracking"], 0)
        if uni:
            cmap[uni] = name

    names = [".notdef", "space", "uni00A0"] + [n for n in order if n in charstrings]
    # line metrics from ASCII (so accented caps don't inflate line height);
    # win metrics cover everything so nothing clips on Windows.
    asc, desc = round(line_max), round(line_min)

    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(f"{FAMILY}-Regular", {"FullName": f"{FAMILY} Regular", "FamilyName": FAMILY,
                                       "Weight": "Regular", "version": VERSION, "Notice": COPYRIGHT},
                charstrings, {})
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=asc, descent=desc, lineGap=tune["lineGap"])
    fb.setupNameTable({
        "copyright": COPYRIGHT,
        "familyName": FAMILY,
        "styleName": "Regular",
        "uniqueFontIdentifier": f"{VERSION};NONE;{FAMILY}-Regular",
        "fullName": f"{FAMILY} Regular",
        "version": f"Version {VERSION}",
        "psName": f"{FAMILY}-Regular",
        "designer": DESIGNER,
        "description": f"{FAMILY} — a handwriting font made from {DESIGNER}'s own handwriting.",
    })
    fb.setupOS2(version=4, sTypoAscender=asc, sTypoDescender=desc, sTypoLineGap=tune["lineGap"],
                usWinAscent=round(win_max), usWinDescent=-round(win_min), sxHeight=XH, sCapHeight=cap_h,
                fsSelection=0x40 | 0x80, fsType=0, achVendID="NONE",
                ulCodePageRange1=1)                    # Latin-1
    fb.setupPost(underlinePosition=-150, underlineThickness=60)
    fb.font["head"].fontRevision = float(VERSION)

    fea = features(names, tune["kerning"], accent_base)
    addOpenTypeFeaturesFromString(fb.font, fea)
    fb.font["OS/2"].recalcUnicodeRanges(fb.font)

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{FAMILY}-Regular.otf"
    fb.save(out)
    (out_dir / "features.fea").write_text(fea)
    info = {"glyphs": {n: {"adv": metrics[n][0], "lsb": metrics[n][1], "ink": ink.get(n, 0),
                           "base": base_of(n, accent_base), "dy": dys.get(n, 0)} for n in names},
            "sidebearing": sb, "space": tune["space"], "tracking": tune["tracking"],
            "lineGap": tune["lineGap"],
            "cmap": {chr(u): n for u, n in cmap.items()}, "xHeight": XH, "capHeight": cap_h,
            "ascent": asc, "descent": desc}
    (out_dir / "font_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(f"wrote {out.relative_to(ROOT)}  ({len(names)} glyphs, asc {asc}, desc {desc}, xh {XH})")


def features(names, kerning, accent_base):
    have = set(names)
    family = {}
    for n in names:
        family.setdefault(base_of(n, accent_base), []).append(n)
    alt2 = [n[:-5] for n in names if n.endswith(".alt2")]
    base = [b for b in alt2 if b in have]
    s1 = [n for n in names if n not in (".notdef", "space", "uni00A0") and "." not in n.strip(".")]
    lines = ["languagesystem DFLT dflt;", "languagesystem latn dflt;"]
    if base:
        b2 = " ".join(f"{b}.alt2" for b in base)
        b3src = [b for b in base if f"{b}.alt3" in have]
        lines += [
            "# cycle versions 1 → 2 → 3 across a word so repeats don't look stamped",
            f"@V1 = [{' '.join(s1)}];",
            f"@V2 = [{' '.join(n for n in names if n.endswith('.alt2'))}];",
            f"@B2 = [{' '.join(base)}];",
            f"@A2 = [{b2}];",
        ]
        if b3src:
            lines += [f"@B3 = [{' '.join(b3src)}];",
                      f"@A3 = [{' '.join(b + '.alt3' for b in b3src)}];"]
        lines += ["lookup cycle {", "  sub @V1 @B2' by @A2;"]
        if b3src:
            lines += ["  sub @V2 @B3' by @A3;"]
        lines += ["} cycle;", "feature calt { lookup cycle; } calt;"]
    if kerning:
        lines.append("feature kern {")
        for pair, v in kerning.items():
            a, b = pair.split()
            if a in have and b in have and v:
                fa, fb_ = " ".join(family.get(a, [a])), " ".join(family.get(b, [b]))
                lines.append(f"  enum pos [{fa}] [{fb_}] {int(v)};")
        lines.append("} kern;")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else sorted((ROOT / "input").glob("*.psd"))[-1]
    main(src)
