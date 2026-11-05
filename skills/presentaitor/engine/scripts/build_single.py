import base64
import mimetypes
import re
import sys
from pathlib import Path

args = [a for a in sys.argv[1:] if a != "--no-audio"]
no_audio = "--no-audio" in sys.argv
src, out = Path(args[0]).resolve(), Path(args[1])
root = src.parent
html = src.read_text()


def local(ref):
    return not re.match(r"(?:[a-z]+:|//|#|\$\{)", ref)


TYPES = {".m4a": "audio/mp4", ".wav": "audio/wav", ".ttf": "font/ttf", ".otf": "font/otf", ".woff2": "font/woff2"}


def data_uri(path):
    if not path.exists():
        print(f"skipped missing {path} (left empty)")
        return ""
    mime = TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


html = re.sub(r'<link rel="stylesheet" href="([^"]+)">',
              lambda m: f"<style>\n{(root / m[1]).read_text()}\n</style>" if local(m[1]) else m[0], html)
html = re.sub(r'<script src="([^"]+)"></script>',
              lambda m: "<script>\n" + (root / m[1]).read_text().replace("</script", "<\\/script") + "\n</script>" if local(m[1]) else m[0], html)
html = re.sub(r'(<(img|audio|source|video)\b[^>]*\bsrc=")([^"]+)(")',
              lambda m: m[1] + ("" if no_audio and m[2] in ("audio", "source") else data_uri(root / m[3])) + m[4] if local(m[3]) else m[0], html)

left = [r for r in re.findall(r'(?:src|href)="([^"]+)"', html) if not r.startswith(("data:", "${", "#"))]
assert not left, f"still external: {left}"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print(out, f"{out.stat().st_size / 1e6:.1f} MB")
