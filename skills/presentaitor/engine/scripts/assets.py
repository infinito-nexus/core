import argparse
import base64
import json
import mimetypes
from pathlib import Path

TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2", ".svg": "image/svg+xml"}


def data_uri(path):
    path = Path(path)
    mime = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if not mime:
        raise SystemExit(f"{path}: unknown file type")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def pair(spec):
    name, sep, path = spec.partition("=")
    if not sep or not name or not path:
        raise argparse.ArgumentTypeError(f"{spec!r}: expected name=file")
    if not Path(path).is_file():
        raise argparse.ArgumentTypeError(f"{path}: no such file")
    return name, path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--font", type=pair, action="append", default=[])
    ap.add_argument("--img", type=pair, action="append", default=[])
    ap.add_argument("--sym")
    a = ap.parse_args()

    fonts = []
    for name, path in a.font:
        family, _, weight = name.partition(":")
        fonts.append({"family": family, "weight": weight or "100 900", "src": data_uri(path)})
    img = {name: data_uri(path) for name, path in a.img}
    sym = {}
    if a.sym:
        folder = Path(a.sym)
        for key, size in json.loads((folder / "manifest.json").read_text()).items():
            name, weight = key.split("@")
            sym[key] = {"src": data_uri(folder / f"{name}__{weight}.png"), "w": round(size["w"], 4), "h": round(size["h"], 4)}

    out = Path(a.out)
    out.write_text("window.ASSETS = " + json.dumps({"fonts": fonts, "img": img, "sym": sym}, separators=(",", ":")) + ";\n")
    print(f"{out}: {len(fonts)} fonts, {len(img)} images, {len(sym)} symbols, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
