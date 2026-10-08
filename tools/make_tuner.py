"""Write font_tuner.html — a self-contained spacing / kerning / leading editor
for the current build. Re-run after every build_font.py.

    .venv/bin/python tools/make_tuner.py
"""
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

font = (BUILD / "Shii-Regular.otf").read_bytes()
info = json.loads((BUILD / "font_info.json").read_text())
tuning_file = ROOT / "tuning.json"
tuning = {"sidebearing": info["sidebearing"], "space": info["space"], "tracking": info["tracking"],
          "lineGap": info["lineGap"], "glyphs": {}, "kerning": {}}
if tuning_file.exists():
    tuning.update(json.loads(tuning_file.read_text()))
stamp = hashlib.sha1(json.dumps(tuning, sort_keys=True).encode()).hexdigest()[:12]

html = (Path(__file__).parent / "tuner_template.html").read_text()
html = (html.replace("__FONT_B64__", base64.b64encode(font).decode())
            .replace("__INFO__", json.dumps(info, ensure_ascii=False))
            .replace("__TUNING__", json.dumps(tuning, ensure_ascii=False))
            .replace("__STAMP__", stamp))
out = ROOT / "font_tuner.html"
out.write_text(html)
print("wrote", out.name, f"({len(html) // 1024} KB)")
