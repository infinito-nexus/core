"""Join a series into one long video with chapter markers.

Order: the intro, then for each chapter a title card ("Chapter N · Title", TITLE_SECONDS) and
the chapter, then the end card. The chapter renders are reused as they are. One ffmpeg
re-encode with hard video cuts (-crf 26 -r 30). Every chapter keeps its own mix; the title
cards carry the series music, which overlaps each neighbour by XFADE seconds with matching
fades, so every break is a 1 s audio crossfade without moving the picture.

Series folder: SERIES.md ("Output: split|long|both", optional "Intro: <folder>" and
"End: <folder>"), and one folder per chapter named NN-<slug> holding voiceover.json.
A chapter's title is voiceover.json "title", else its slug.

Output in <series>/out/: <series>-long.mp4 (with MP4 chapters), chapters.txt (YouTube) and
<series>-long.html (player with a chapter menu).
"""
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TITLE_SECONDS = 2.5
XFADE = 1.0


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    return float(j["format"]["duration"]), v["width"], v["height"]


def notes(series):
    p = series / "SERIES.md"
    return p.read_text() if p.exists() else ""


def field(text, name):
    m = re.search(rf"^{name}:\s*(\S+)", text, re.I | re.M)
    return m.group(1) if m else None


def video_of(film):
    for name in (f"{film.name}.mp4", f"{film.name}-draft.mp4"):
        if (film / "out" / name).exists():
            return film / "out" / name
    raise SystemExit(f"{film.name}: no render in {film / 'out'}; run film.py render first")


def title_of(film):
    spec = json.loads((film / "voiceover.json").read_text())
    return spec.get("title") or re.sub(r"^\d+-", "", film.name).replace("-", " ").capitalize()


def meta_escape(text):
    return re.sub(r"([=;#\\])", r"\\\1", text)


def stamp(sec):
    s = int(round(sec))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def title_card(series, film, n, size, work):
    """Render the title card of chapter n in the brand of that chapter. Output: the card's video."""
    card = work / f"title-{n:02d}"
    if card.exists():
        shutil.rmtree(card)
    (card / "src").mkdir(parents=True)
    for f in (SKILL / "engine" / "templates" / "shared").iterdir():
        shutil.copy(f, card / "src" / f.name)
    for f in ("film.css", "assets.js"):
        shutil.copy(film / "src" / f, card / "src" / f)
    (card / "src" / "device.js").write_text("")
    shutil.copy(SKILL / "defaults" / "scenes" / "title-card.js", card / "src" / "scenes.js")
    (card / "src" / "timing.js").write_text("window.TIMING = null;\n" + "window.TITLE_CARD = " + json.dumps(
        {"n": n, "title": title_of(film), "W": size[0], "H": size[1], "seconds": TITLE_SECONDS}) + ";\n")
    out = card / "card.mp4"
    subprocess.run(["node", str(SKILL / "engine" / "scripts" / "render.mjs"), "video", str(card / "src" / "index.html"), str(out), "--crf", "18", "--fps", "30"], check=True)
    return out


def main(series, only_if_configured=False):
    series = Path(series)
    text = notes(series)
    fmt = (field(text, "Output") or "both").lower()
    if fmt == "split":
        if not only_if_configured:
            print("SERIES.md says Output: split; no long video")
        return
    films = [p for p in sorted(series.iterdir()) if p.is_dir() and re.match(r"\d\d", p.name) and (p / "voiceover.json").exists()]
    intro = series / field(text, "Intro") if field(text, "Intro") else next((p for p in films if re.match(r"\d+-intro\b", p.name)), None)
    end = series / field(text, "End") if field(text, "End") else next((p for p in films if re.match(r"\d+-(end|outro)\b", p.name)), None)
    chapters = [p for p in films if p not in (intro, end)]
    if not chapters:
        raise SystemExit(f"{series}: no chapter folders (NN-<slug> with voiceover.json) besides the intro and end")
    work = series / "out" / "long"
    work.mkdir(parents=True, exist_ok=True)
    music = json.loads((chapters[0] / "voiceover.json").read_text())
    bed = (chapters[0] / music["music"]).resolve()

    items = []
    if intro:
        items.append({"kind": "film", "video": video_of(intro), "title": "Intro"})
    for ch in chapters:
        n = int(re.match(r"\d+", ch.name).group())
        size = probe(video_of(ch))[1:]
        items.append({"kind": "card", "video": title_card(series, ch, n, size, work)})
        items.append({"kind": "film", "video": video_of(ch), "title": f"Chapter {n} · {title_of(ch)}"})
    if end:
        items.append({"kind": "film", "video": video_of(end), "title": "End"})

    W, H = probe(items[0]["video"])[1:] if items[0]["kind"] == "film" else probe(items[1]["video"])[1:]
    t, marks = 0.0, []
    for it in items:
        it["start"], it["dur"] = t, probe(it["video"])[0]
        t += it["dur"]
    total = t
    for i, it in enumerate(items):
        if it["kind"] == "film":
            marks.append((items[i - 1]["start"] if i and items[i - 1]["kind"] == "card" else it["start"], it["title"]))

    args, vf, af, mix = ["ffmpeg", "-v", "error", "-y"], [], [], []
    for it in items:
        args += ["-i", str(it["video"])]
    args += ["-stream_loop", "-1", "-i", str(bed)]
    nb = len(items)
    for i, it in enumerate(items):
        vf.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
                  f"trim=duration={it['dur']:.4f},setpts=PTS-STARTPTS[v{i}]")
        prev = items[i - 1]["kind"] if i else None
        nxt = items[i + 1]["kind"] if i + 1 < nb else None
        if it["kind"] == "film":
            fades = []
            if prev == "card":
                fades.append(f"afade=t=in:d={XFADE}:curve=qsin")
            if nxt == "card":
                fades.append(f"afade=t=out:st={it['dur'] - XFADE:.4f}:d={XFADE}:curve=qsin")
            af.append(f"[{i}:a]aresample=44100,atrim=duration={it['dur']:.4f}{',' + ','.join(fades) if fades else ''},"
                      f"adelay={round(it['start'] * 1000)}:all=1[a{i}]")
        else:
            lead = XFADE if i and items[i - 1]["kind"] == "film" else 0.0
            tail = XFADE if nxt == "film" else 0.0
            length = it["dur"] + lead + tail
            af.append(f"[{nb}:a]aresample=44100,atrim=start=30:duration={length:.4f},asetpts=PTS-STARTPTS,loudnorm=I=-24:TP=-2,aresample=44100,"
                      f"afade=t=in:d={max(lead, 0.05)}:curve=qsin,afade=t=out:st={length - max(tail, 0.05):.4f}:d={max(tail, 0.05)}:curve=qsin,"
                      f"adelay={round((it['start'] - lead) * 1000)}:all=1[a{i}]")
        mix.append(f"[a{i}]")
    graph = ";".join(vf + af) + ";" + "".join(f"[v{i}]" for i in range(nb)) + f"concat=n={nb}:v=1:a=0[v];" + \
        "".join(mix) + f"amix=inputs={nb}:normalize=0,atrim=duration={total:.4f}[a]"

    meta = work / "chapters.ffmeta"
    meta.write_text(";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={round(s * 1000)}\nEND={round((marks[k + 1][0] if k + 1 < len(marks) else total) * 1000)}\ntitle={meta_escape(name)}\n"
        for k, (s, name) in enumerate(marks)))
    out = series / "out" / f"{series.name}-long.mp4"
    subprocess.run(args + ["-i", str(meta), "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-map_chapters", str(nb + 1),
                           "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-r", "30", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    if marks[0][0] > 0:
        marks.insert(0, (0.0, "Intro"))
    (series / "out" / "chapters.txt").write_text("".join(f"{stamp(s)} {name}\n" for s, name in marks))
    menu = "".join(f'<li><button type="button" data-t="{s:.3f}">{stamp(s)} · {html.escape(name)}</button></li>' for s, name in marks)
    (series / "out" / f"{series.name}-long.html").write_text(PLAYER.format(title=html.escape(series.name), video=html.escape(out.name), menu=menu))
    print(f"{out}: {total:.2f}s, {len(marks)} chapters; chapters.txt and {series.name}-long.html written")


PLAYER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#0f1218; --ink:#e9edf2; --ink2:#9aa4b2; --card:#1a1f27; --accent:#4f6bff; }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--ink); font:15px/1.4 system-ui,sans-serif; }}
main {{ display:grid; grid-template-columns:minmax(0,1fr) 280px; gap:16px; max-width:1400px; margin:0 auto; }}
@media (max-width:800px) {{ main {{ grid-template-columns:1fr; }} }}
video {{ width:100%; border-radius:10px; background:#000; }}
ol {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }}
button {{ width:100%; text-align:left; background:var(--card); color:inherit; border:2px solid transparent; border-radius:8px; padding:10px 12px; font:inherit; cursor:pointer; font-variant-numeric:tabular-nums; }}
button[aria-current="true"] {{ border-color:var(--accent); }}
</style></head><body>
<main><video id="v" src="{video}" controls preload="metadata"></video>
<nav aria-label="Chapters"><ol id="menu">{menu}</ol></nav></main>
<script>
const v = document.getElementById("v"), items = [...document.querySelectorAll("#menu button")];
items.forEach((b) => b.addEventListener("click", () => {{ v.currentTime = Number(b.dataset.t); v.play(); }}));
v.addEventListener("timeupdate", () => {{
  let cur = items[0];
  for (const b of items) if (v.currentTime >= Number(b.dataset.t) - 0.05) cur = b;
  items.forEach((b) => b.setAttribute("aria-current", String(b === cur)));
}});
</script></body></html>
"""
