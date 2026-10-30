# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow"]
# ///
import glob
import sys

from PIL import Image, ImageDraw

out, folder = sys.argv[1], sys.argv[2]
bpm = float(sys.argv[3]) if len(sys.argv) > 3 else 0
files = sorted(glob.glob(folder + "/t*.png"), key=lambda f: float(f.rsplit("/t", 1)[1][:-4]))
if not files:
    sys.exit(f"no t*.png frames in {folder}")
first = Image.open(files[0])
if len(sys.argv) > 4:
    tw = int(sys.argv[4])
    th = round(tw * first.height / first.width)
    cols, rows = max(1, 1568 // (tw + 8)), max(1, 1568 // (th + 26))
    per_page = cols * rows
else:
    cols, th, per_page = 6, 300, 24
    tw = round(th * first.width / first.height)
pages = [files[i:i + per_page] for i in range(0, len(files), per_page)]
for n, chunk in enumerate(pages, 1):
    rows = (len(chunk) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 8), rows * (th + 26)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for k, f in enumerate(chunk):
        t = float(f.rsplit("/t", 1)[1][:-4])
        x, y = (k % cols) * (tw + 8), (k // cols) * (th + 26)
        sheet.paste(Image.open(f).convert("RGB").resize((tw, th)), (x, y + 22))
        label = f"{t:.2f}s" + (f"  beat {int(t / (60 / bpm)) + 1}" if bpm else "")
        draw.text((x + 3, y + 5), label, fill=(20, 26, 21))
    path = out if len(pages) == 1 else out[:-4] + f"-{n}.png"
    sheet.save(path)
    print(path)
