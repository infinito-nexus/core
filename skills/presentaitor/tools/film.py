"""presentaitor film commands: voice-first render, preview, one chapter of a series, playground, join.

Usage:
    film.py render <film> [--final]            voice, timing, footage, picture by scene, mix, silence check
    film.py preview <film>                     30 fps, half scale, no blur accumulation, then the contact sheet
    film.py render <series> --chapter NN [--final]
    film.py join <series>                      the long video and chapter markers (SERIES.md "Output")
    film.py playground [preset] [--check] [--apply defaults.json]
                                               one test page per motion preset

A film folder holds voiceover.json (with "scenes"), src/index.html and audio/.
Picture segments are cached per scene in out/segments/<profile>/: a scene renders again only
when its timing, its footage windows, the page code or the profile changed.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / "engine" / "scripts"
CACHE = Path(os.environ.get("PRESENTAITOR_CACHE", "/tmp/presentaitor-cache"))
LOCAL_HF = Path.home() / ".cache" / "huggingface"
ENV = {
    **os.environ,
    "NUMBA_CACHE_DIR": str(CACHE / "numba"),
    "HF_HOME": os.environ.get("HF_HOME", str(LOCAL_HF if (LOCAL_HF / "hub").exists() else CACHE / "hf")),
    **({"HF_HUB_OFFLINE": "1"} if (LOCAL_HF / "hub" / "models--ResembleAI--chatterbox").exists() else {}),
}
PROFILES = {
    "preview": {"fps": 30, "scale": 0.5, "crf": "26", "blur": False, "suffix": "-preview"},
    "draft": {"fps": None, "scale": 1, "crf": "20", "blur": False, "suffix": "-draft"},
    "final": {"fps": None, "scale": 1, "crf": "14", "blur": True, "suffix": ""},
}
sys.path.insert(0, str(ENGINE))
import footage  # noqa: E402
import silence  # noqa: E402


def run(*args, **kw):
    print("$ " + " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], check=True, env=ENV, **kw)


def digest(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def code_key(src):
    h = hashlib.sha1()
    for p in sorted(src.iterdir()):
        if p.is_file() and p.name != "timing.js":
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def stamped(path, key):
    stamp = path.with_name(path.name + ".key")
    return path.exists() and stamp.exists() and stamp.read_text().strip() == key


def stamp(path, key):
    path.with_name(path.name + ".key").write_text(key + "\n")


def output_format(series):
    """Args: a series folder. Output: "split", "long" or "both" from the "Output:" line of its SERIES.md (default both)."""
    notes = Path(series) / "SERIES.md"
    m = re.search(r"^output:\s*(split|long|both)\b", notes.read_text() if notes.exists() else "", re.I | re.M)
    return m.group(1).lower() if m else "both"


def captions_default(film):
    """Captions are on by default for a series with a long video and for phone films, off elsewhere."""
    device = film / "src" / "device.js"
    phone = device.exists() and "devBody" in device.read_text()
    series = (film.parent / "SERIES.md").exists() and output_format(film.parent) in ("long", "both")
    return phone or series


def voice(film):
    ENV["PRESENTAITOR_CAPTIONS"] = "1" if captions_default(film) else "0"
    run("python3", ENGINE / "voiceover.py", film / "voiceover.json")
    return json.loads((film / "voiceover.json").read_text()), json.loads((film / "timing.json").read_text())


def cut_footage(film, spec, plan):
    if "footage" not in spec:
        return None
    dst = film / spec["footage"].get("out", "footage.mp4")
    src = (film / spec["footage"]["src"]).resolve()
    key = digest(footage.windows(plan), plan["fps"], src.stat().st_mtime, src.stat().st_size)
    if stamped(dst, key):
        print(f"footage unchanged: {dst.name}")
    else:
        run("python3", ENGINE / "footage.py", film)
        stamp(dst, key)
    return dst


def camera_footage(film, under, plan):
    """Zoom the footage with the page's window.FOOTAGE_CAMERA, if it defines one. Output: the footage to draw under the page."""
    cams = film / "out" / "camera.json"
    run("node", ENGINE / "camera.mjs", film / "src/index.html", cams, plan["fps"])
    cam = json.loads(cams.read_text())
    if not cam["frames"]:
        return under, None
    dst = under.with_name(under.stem + "-camera.mp4")
    src_key = under.with_name(under.name + ".key")
    key = digest(cam, src_key.read_text() if src_key.exists() else under.stat().st_mtime)
    if stamped(dst, key):
        print(f"camera footage unchanged: {dst.name}")
        return dst, cam["frames"]
    fw, fh = [int(v) for v in subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                               "-of", "csv=p=0", str(under)], capture_output=True, text=True, check=True).stdout.strip().split(",")]
    from PIL import Image
    W, H, kx, ky, fps = cam["W"], cam["H"], fw / cam["W"], fh / cam["H"], cam["fps"]
    size = fw * fh * 3
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(under), "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{fw}x{fh}", "-r", str(fps), "-i", "-",
                            "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", str(dst)], stdin=subprocess.PIPE)
    for x, y, s in cam["frames"]:
        raw = dec.stdout.read(size)
        if len(raw) < size:
            break
        tx = min(max(W / 2 - x * s, W - W * s), 0)
        ty = min(max(H / 2 - y * s, H - H * s), 0)
        box = (-tx / s * kx, -ty / s * ky, (-tx + W) / s * kx, (-ty + H) / s * ky)
        frame = Image.frombytes("RGB", (fw, fh), raw)
        enc.stdin.write((frame if s <= 1.0001 else frame.resize((fw, fh), Image.LANCZOS, box=box)).tobytes())
    dec.stdout.close()
    dec.wait()
    enc.stdin.close()
    if enc.wait():
        raise SystemExit(f"ffmpeg could not encode {dst}")
    stamp(dst, key)
    return dst, cam["frames"]


def scene_windows(plan, scene):
    return [w for w in footage.windows(plan) if w[0] < round(scene["end"] * plan["fps"]) and w[1] > round(scene["start"] * plan["fps"])]


def render(film, profile, blur=1):
    """Render a film with a profile. Output: (video path, seconds spent on the picture, silence findings, ok)."""
    film = Path(film).resolve()
    prof = PROFILES[profile]
    spec, plan = voice(film)
    under = cut_footage(film, spec, plan)
    cam = None
    if under:
        under, cam = camera_footage(film, under, plan)
    fps = prof["fps"] or plan["fps"]
    code = code_key(film / "src")
    seg_dir = film / "out" / "segments" / profile
    seg_dir.mkdir(parents=True, exist_ok=True)
    started, segments, rendered = time.time(), [], []
    for sc in plan["scenes"]:
        f0, f1 = round(sc["start"] * fps), round(sc["end"] * fps)
        seg = seg_dir / f"{sc['id']}.mp4"
        key = digest(profile, fps, f0, f1, sc, [plan["lines"][lid] for lid in sc["lines"]],
                     plan.get("captions"), [plan.get("words", {}).get(lid) for lid in sc["lines"]],
                     scene_windows(plan, sc) if under else None, code, blur if prof["blur"] else 1,
                     cam[round(sc["start"] * plan["fps"]):round(sc["end"] * plan["fps"])] if cam else None,
                     under.with_name(under.name + ".key").read_text() if under and under.with_name(under.name + ".key").exists() else None)
        segments.append(seg)
        if stamped(seg, key):
            print(f"scene {sc['id']:10s} unchanged, reused")
            continue
        rendered.append(sc["id"])
        args = ["node", ENGINE / "render.mjs", "video", film / "src/index.html", seg, "--from", f"{f0 / fps:.6f}", "--to", f"{f1 / fps:.6f}",
                "--crf", prof["crf"], "--fps", fps, "--scale", prof["scale"]]
        if under:
            args += ["--under", under]
        if prof["blur"] and blur > 1:
            args += ["--blur", blur]
        if profile == "preview":
            args.append("--preview")
        run(*args)
        stamp(seg, key)
    picture = time.time() - started
    listing = seg_dir / "concat.txt"
    listing.write_text("".join(f"file '{s}'\n" for s in segments))
    out = film / "out" / f"{film.name}{prof['suffix']}.mp4"
    mix = film / (spec["out"] + ".m4a")
    run("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing, "-i", mix,
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", out)
    found, ok = silence.check(film)
    for level, a, b, sc in found:
        print(f"{level} {a:7.2f}-{b:7.2f}s  {b - a:.2f}s without speech  scene {sc}")
    print(f"{out}: {len(rendered)} of {len(segments)} scenes rendered ({', '.join(rendered) or 'none'}), picture {picture:.0f}s; "
          f"silence check {'pass' if ok else 'FAIL'}")
    return out, picture, found, ok


def chapter_dir(series, nn):
    hits = [p for p in sorted(Path(series).iterdir()) if p.is_dir() and p.name.startswith(f"{int(nn):02d}")]
    if len(hits) != 1:
        raise SystemExit(f"chapter {nn}: expected one folder starting with {int(nn):02d} in {series}, found {[p.name for p in hits]}")
    return hits[0]


def main():
    if sys.argv[1:2] == ["playground"]:
        import playground
        playground.main(sys.argv[2:])
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["render", "preview", "join", "playground"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--chapter")
    ap.add_argument("--blur", type=int, default=1)
    a = ap.parse_args()
    if a.command == "join":
        import join
        join.main(Path(a.target).resolve())
        return
    film = chapter_dir(a.target, a.chapter) if a.chapter else Path(a.target)
    if a.command == "preview":
        import contact_sheet
        out, _, found, ok = render(film, "preview")
        print(contact_sheet.write(Path(film).resolve(), out, found))
    else:
        out, _, found, ok = render(film, "final" if a.final else "draft", a.blur)
        if a.chapter:
            import join
            join.main(Path(a.target).resolve(), only_if_configured=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
