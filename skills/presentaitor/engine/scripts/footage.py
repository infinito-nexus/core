"""Cut a film's footage to its voice-first timing.

Args:
    argv[1]: the film folder, holding voiceover.json and timing.json.

voiceover.json gives "footage": {"src": <source video>, "out": <derived video, default footage.mp4>}.
Each line's "clip": [from, to] is the part of the source shown from the line's window start
(the scene start for a scene's first line, else the previous line's slot end) to its slot end.
A clip shorter than its window plays at 1x and holds its last frame (the freeze sized to the
line plus the gap); a longer clip is sped up to at most MAX_SPEED, then cut. A line without a
clip, or a music-only scene without one, holds the previous frame.

Output:
    the derived video, video only, at the timing's fps, frame-exact to timing.json.
"""
import json
import subprocess
import sys
from pathlib import Path

MAX_SPEED = 1.5


def windows(plan):
    """Args: a timing dict. Output: [(first frame, last frame, clip or None)] covering the whole film."""
    fps, out, prev = plan["fps"], [], None
    for sc in plan["scenes"]:
        w0 = sc["start"]
        if not sc["lines"]:
            out.append((round(w0 * fps), round(sc["end"] * fps), sc.get("clip")))
            continue
        for lid in sc["lines"]:
            ln = plan["lines"][lid]
            out.append((round(w0 * fps), round(ln["slot"] * fps), ln.get("clip")))
            w0 = ln["slot"]
    fixed = []
    for a, b, clip in out:
        if clip is None and prev is not None:
            clip = [prev[1] - 0.05, prev[1] - 0.05]
        if clip is not None:
            prev = clip
        fixed.append((a, b, clip))
    return [w for w in fixed if w[1] > w[0]]


def main():
    base = Path(sys.argv[1]).resolve()
    spec = json.loads((base / "voiceover.json").read_text())
    plan = json.loads((base / "timing.json").read_text())
    cfg = spec["footage"]
    src, dst = (base / cfg["src"]).resolve(), base / cfg.get("out", "footage.mp4")
    fps, chains = plan["fps"], []
    segs = windows(plan)
    if segs[0][2] is None:
        raise SystemExit("the first line or scene has no \"clip\": nothing to show at the start")
    for i, (f0, f1, (a, b)) in enumerate(segs):
        if b < a:
            raise SystemExit(f"window at {f0 / fps:.2f}s: clip [{a}, {b}] ends before it starts")
        need, have = (f1 - f0) / fps, max(b - a, 0.0)
        speed = min(have / need, MAX_SPEED) if have > need else 1.0
        if speed > 1.0:
            print(f"window {f0 / fps:7.2f}s: clip {have:.2f}s into {need:.2f}s at {speed:.2f}x" + (", cut" if have / need > MAX_SPEED else ""))
        chains.append(f"[0:v]trim=start={a:.4f}:end={a + max(have, 1 / fps):.4f},setpts=(PTS-STARTPTS)/{speed:.4f},fps={fps},"
                      f"tpad=stop_mode=clone:stop_duration={need + 1:.4f},trim=end_frame={f1 - f0},setpts=PTS-STARTPTS[v{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0[out]"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", graph, "-map", "[out]", "-an",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", str(dst)], check=True)
    print(f"{dst}: {segs[-1][1]} frames ({segs[-1][1] / fps:.2f}s), {len(segs)} windows")


if __name__ == "__main__":
    main()
