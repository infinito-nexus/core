"""Voice-first timing: lay a chapter out from the measured length of its takes.

The script's "scenes" list the lines in order. Every line starts GAP after the
previous one inside a scene; a scene ends TAIL after its last line, snapped to
the nearest half beat, and the next scene's first line starts so that a scene
change leaves SCENE_GAP of air (more only when a long snap or "min" forces it). A scene with "music": seconds
holds no lines (an intro or outro under music only).

Scene keys: id, lines (ids in order), music (seconds, music-only scene),
lead and tail (seconds, override the defaults), min (shortest scene, seconds).
Line keys used here: id, hold (extra seconds after the line for action on screen),
clip ([from, to] seconds of source footage shown during the line).
"""
import hashlib
import json
from pathlib import Path

GAP = 0.35
SCENE_GAP = 0.8
TAIL = SCENE_GAP / 2
MIN_LEAD = 0.2
FIRST_LEAD = 0.6


def take_key(line, settings, backend):
    """Args: a script line, its voice's settings, the backend. Output: the cache key of its take."""
    blob = json.dumps([line["text"], settings, backend], sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


def snap_half_beat(x, bpm, least):
    """Args: a time, the tempo, the earliest allowed result. Output: the half beat nearest x, not before least."""
    half = 30.0 / bpm
    v = round(x / half) * half
    while v < least - 1e-9:
        v += half
    return round(v, 4)


def layout(scenes, lines, durs, bpm, fps):
    """Lay out a chapter.

    Args:
        scenes: the script's scenes (see the module docstring).
        lines: the script's lines, by id.
        durs: trimmed take length in seconds, by line id.
        bpm: tempo of the music bed, for the half-beat snap.
        fps: frame rate, for the frame count.

    Output:
        the timing dict written to timing.json: fps, bpm, duration, frames, scenes, lines.
    """
    t, out_scenes, out_lines, tail = 0.0, [], {}, None
    for sc in scenes:
        start = t
        if sc.get("music") is not None:
            end = snap_half_beat(start + sc["music"], bpm, start + 0.5)
            out_scenes.append({"id": sc["id"], "start": round(start, 4), "end": end, "music": True, "lines": []})
            t, tail = end, None
            continue
        if not sc.get("lines"):
            raise ValueError(f"scene {sc['id']} has no lines and no \"music\" length")
        lead = FIRST_LEAD if tail is None else max(SCENE_GAP - tail, MIN_LEAD)
        cur = start + sc.get("lead", lead)
        last = None
        for lid in sc["lines"]:
            if lid not in lines:
                raise ValueError(f"scene {sc['id']} names line {lid}, which the script does not have")
            d = durs[lid]
            entry = {"start": round(cur, 4), "end": round(cur + d, 4), "scene": sc["id"], "text": lines[lid]["text"]}
            if "clip" in lines[lid]:
                entry["clip"] = lines[lid]["clip"]
            out_lines[lid] = entry
            last = cur + d + lines[lid].get("hold", 0.0)
            if lid != sc["lines"][-1]:
                entry["slot"] = round(last + GAP, 4)
            cur = last + GAP
        raw = max(last + sc.get("tail", TAIL), start + sc.get("min", 0.0))
        end = snap_half_beat(raw, bpm, last + 0.2)
        out_lines[sc["lines"][-1]]["slot"] = end
        out_scenes.append({"id": sc["id"], "start": round(start, 4), "end": end, "lines": list(sc["lines"])})
        t, tail = end, end - last
    frames = round(t * fps)
    return {"fps": fps, "bpm": bpm, "duration": round(frames / fps, 4), "frames": frames,
            "scenes": out_scenes, "lines": out_lines}


def first_change(old, new):
    """Args: the previous and the new timing dict (old may be None). Output: id of the first scene whose timing changed, or None."""
    before = {s["id"]: s for s in (old or {}).get("scenes", [])}
    for s in new["scenes"]:
        o = before.get(s["id"])
        mine = [new["lines"][lid] for lid in s["lines"]]
        theirs = [(old or {}).get("lines", {}).get(lid) for lid in s["lines"]]
        if not o or (o["start"], o["end"], o["lines"]) != (s["start"], s["end"], s["lines"]) or mine != theirs:
            return s["id"]
    return None


def write(timing, base, src="src"):
    """Write timing.json in the film folder and src/timing.js for the page.

    Args:
        timing: dict from layout().
        base: the film folder.
        src: the page folder, relative to base.

    Output:
        id of the first scene whose timing changed since the last write, or None.
    """
    path = Path(base) / "timing.json"
    old = json.loads(path.read_text()) if path.exists() else None
    changed = first_change(old, timing)
    path.write_text(json.dumps(timing, indent=1) + "\n")
    page = Path(base) / src
    if page.is_dir():
        (page / "timing.js").write_text("window.TIMING = " + json.dumps(timing) + ";\n")
    return changed
