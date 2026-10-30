"""Re-time a voiceover.json to the cached takes of its backend.

Args:
    argv[1]: path to voiceover.json; rewritten in place.

Per line, in order: keep the planned start if the take fits before the next line;
otherwise pull the start earlier into free space (at most PULL s, never before the
previous line's end + GAP), then allow a gentle speed-up (at most MAX_TEMPO via
"until"), and only then push the next line later.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "scripts"))
from voiceover import duration, trimmed  # noqa: E402

GAP = 0.25
PULL = 0.8
MAX_TEMPO = 1.12

path = Path(sys.argv[1])
spec = json.loads(path.read_text())
length = spec["frames"] / spec.get("fps", 60)
cache = path.parent / "out/voiceover" / spec.get("backend", "chatterbox")
lines = sorted(spec["lines"], key=lambda ln: ln["start"])

with tempfile.TemporaryDirectory() as t:
    durs = [duration(trimmed(cache / f"{ln['id']}.wav", Path(t) / f"{ln['id']}.wav")) for ln in lines]

prev_end = 0.0
for i, ln in enumerate(lines):
    ln.pop("until", None)
    d = durs[i]
    nxt = lines[i + 1]["start"] if i + 1 < len(lines) else length - 0.3
    start = max(ln["start"], prev_end + GAP)
    if start + d > nxt - 0.12:
        start = max(prev_end + GAP, min(start, nxt - 0.12 - d), start - PULL)
    end = start + d
    if end > nxt - 0.12:
        fitted = start + d / MAX_TEMPO
        if fitted <= nxt - 0.12:
            ln["until"] = round(nxt - 0.12, 2)
            end = nxt - 0.12
        else:
            ln["until"] = round(fitted, 2)
            end = fitted
            if i + 1 < len(lines):
                lines[i + 1]["start"] = round(end + GAP, 2)
    ln["start"] = round(start, 2)
    prev_end = end
    print(f"{ln['id']}  {ln['start']:6.2f}-{end:6.2f}s  take {d:.2f}s{'  until ' + str(ln['until']) if 'until' in ln else ''}")

if prev_end > length - 0.2:
    print(f"WARNING: speech ends at {prev_end:.2f}s, film is {length:.2f}s")
spec["lines"] = lines
path.write_text(json.dumps(spec, indent=2) + "\n")
