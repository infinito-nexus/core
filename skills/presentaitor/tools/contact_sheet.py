"""Contact sheet: one HTML page per chapter, one card per narration line.

Each card shows a thumbnail from the middle of the line, its text and its start and end
times. Silence-check findings are listed on top and marked on the card they follow.
Clicking a card plays the preview video from the line's start.
"""
import html
import json
import subprocess
from pathlib import Path

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#101318; --card:#1a1f27; --ink:#e9edf2; --ink2:#9aa4b2; --warn:#f2b84b; --fail:#ff6b6b; --accent:#4f6bff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--ink); font:15px/1.4 system-ui,sans-serif; }}
h1 {{ font-size:20px; margin:0 0 12px; }}
#player {{ position:sticky; top:0; z-index:2; background:var(--bg); padding-bottom:12px; }}
video {{ width:min(100%,720px); display:block; border-radius:8px; background:#000; }}
#findings {{ margin:8px 0 0; padding:0; list-style:none; font-variant-numeric:tabular-nums; }}
#findings li {{ margin:2px 0; }}
.WARN {{ color:var(--warn); }} .FAIL {{ color:var(--fail); }}
#grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; }}
.card {{ background:var(--card); border-radius:10px; overflow:hidden; cursor:pointer; border:2px solid transparent; text-align:left; color:inherit; font:inherit; padding:0; }}
.card:hover, .card:focus-visible {{ border-color:var(--accent); outline:none; }}
.card img {{ width:100%; display:block; aspect-ratio:{aspect}; object-fit:cover; background:#000; }}
.meta {{ padding:8px 10px 10px; }}
.time {{ color:var(--ink2); font-size:13px; font-variant-numeric:tabular-nums; }}
.flag {{ font-size:13px; margin-top:4px; }}
</style></head><body>
<div id="player"><h1>{title}</h1><video id="v" src="{video}" controls preload="metadata"></video>
<ul id="findings">{findings}</ul></div>
<div id="grid">{cards}</div>
<script>
const v = document.getElementById("v");
document.querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => {{
  v.currentTime = Number(c.dataset.t);
  v.play();
  window.scrollTo({{ top: 0, behavior: "smooth" }});
}}));
</script></body></html>
"""


def write(film, video, found):
    """Write <film>/out/<name>-sheet.html.

    Args:
        film: the film folder (timing.json).
        video: the preview video, inside <film>/out.
        found: silence findings [(level, start, end, scene)].

    Output:
        the sheet's path.
    """
    plan = json.loads((film / "timing.json").read_text())
    thumbs = film / "out" / "sheet"
    thumbs.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    lines = sorted(plan["lines"].items(), key=lambda kv: kv[1]["start"])
    cards = []
    for lid, ln in lines:
        mid = (ln["start"] + ln["end"]) / 2
        jpg = thumbs / f"{lid}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{mid:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(jpg)], check=True)
        flags = "".join(f'<div class="flag {lv}">{lv} {b - a:.1f}s silence after this line ({a:.2f}-{b:.2f}s)</div>'
                        for lv, a, b, _ in found if ln["end"] - 0.05 <= a <= ln["end"] + 0.6)
        cards.append(f'<button class="card" data-t="{ln["start"]:.3f}"><img src="sheet/{lid}.jpg" alt="{html.escape(lid)} at {mid:.2f}s" loading="lazy">'
                     f'<div class="meta"><div class="time">{lid} · {ln["start"]:.2f}–{ln["end"]:.2f}s · {ln["scene"]}</div>'
                     f'<div>{html.escape(ln["text"])}</div>{flags}</div></button>')
    items = "".join(f'<li class="{lv}">{lv} {a:.2f}–{b:.2f}s ({b - a:.2f}s without speech) in scene {sc}</li>' for lv, a, b, sc in found)
    items = items or "<li>Silence check: no span over 1.2 s.</li>"
    out = film / "out" / f"{film.name}-sheet.html"
    out.write_text(PAGE.format(title=html.escape(f"{film.name} contact sheet"), video=html.escape(Path(video).name),
                               findings=items, cards="".join(cards), aspect=f"{probe[0]}/{probe[1]}"))
    return out
