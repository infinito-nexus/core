"""Preset playground: one test page per motion preset, on the real engine code.

Usage (through film.py):
    film.py playground [preset] [--out DIR]   build the pages and print their file:// links
    film.py playground --check [--out DIR]    also load every page headless, seek it and save stills
    film.py playground --apply FILE.json      merge exported slider values into preset-defaults.js

Adding a technique: its function in engine/templates/shared/presets.js, its defaults in
preset-defaults.js, and a preset(name, {...}) page in engine/playground/demos.js. It enters
the library only after its playground page has been reviewed.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine"
SHARED = ENGINE / "templates" / "shared"
DEFAULTS = SHARED / "preset-defaults.js"


def names():
    return re.findall(r'^preset\("([^"]+)"', (ENGINE / "playground" / "demos.js").read_text(), re.M)


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    for f in ("assets.js", "timing.js", "core.js", "fx.js", "preset-defaults.js", "presets.js"):
        shutil.copy(SHARED / f, out / f)
    shutil.copy(ENGINE / "playground" / "demos.js", out / "demos.js")
    page = (ENGINE / "playground" / "page.html").read_text()
    pages = {}
    for n in names():
        pages[n] = out / f"{n}.html"
        pages[n].write_text(page.replace("<body>", f'<body data-preset="{n}">', 1))
    links = "".join(f'<li><a href="{n}.html">{n}</a></li>' for n in pages)
    (out / "index.html").write_text(f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Preset Playground</title>'
                                    f'<style>body{{background:#0d0f14;color:#e8ebf2;font:16px system-ui;padding:24px}}a{{color:#6aa8ff}}</style></head>'
                                    f'<body><h1>Presets</h1><ul>{links}</ul></body></html>')
    return pages


def apply(path, target=DEFAULTS):
    target = Path(target)
    current = json.loads(target.read_text().split("=", 1)[1].rstrip().rstrip(";"))
    new = json.loads(Path(path).read_text())
    for name, values in new.items():
        if name not in current:
            raise SystemExit(f"{name} is not a preset in {target}")
        unknown = set(values) - set(current[name])
        if unknown:
            raise SystemExit(f"{name}: unknown parameters {sorted(unknown)}")
        current[name].update(values)
    body = ",\n".join(f"  {json.dumps(k)}: {json.dumps(v)}" for k, v in current.items())
    target.write_text("window.PRESET_DEFAULTS = {\n" + body + "\n};\n")
    print(f"{target}: updated {', '.join(new)}")


def main(argv):
    ap = argparse.ArgumentParser(prog="film.py playground")
    ap.add_argument("preset", nargs="?")
    ap.add_argument("--out", default="/tmp/presentaitor-playground")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply")
    ap.add_argument("--defaults", default=str(DEFAULTS))
    a = ap.parse_args(argv)
    if a.apply:
        apply(a.apply, a.defaults)
        return
    pages = build(Path(a.out))
    chosen = {a.preset: pages[a.preset]} if a.preset else pages
    for n, p in chosen.items():
        print(f"{n:12s} {p.as_uri()}")
    if a.check:
        subprocess.run(["node", str(ENGINE / "playground" / "check.mjs"), a.out, *chosen], check=True)
