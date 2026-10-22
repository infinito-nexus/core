"""Silence check: find spans without speech in a voice-first film.

Args:
    argv[1]: the film folder (timing.json, out/voiceover/voice-stem.wav).

Spans longer than WARN print a warning, spans longer than FAIL fail with exit code 1.
Music-only scenes, the intro before the first word and the outro after the last are exempt.

Output:
    one line per finding: level, time range, length, scene.
"""
import json
import subprocess
import sys
from pathlib import Path

WARN = 1.2
FAIL = 2.5
THRESHOLD = "-40dB"


def quiet_spans(stem, least=WARN):
    """Args: a voice-only WAV, the shortest span to report. Output: [(start, end)] below THRESHOLD."""
    log = subprocess.run(["ffmpeg", "-i", str(stem), "-af", f"silencedetect=n={THRESHOLD}:d={least}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x.split("silence_start: ")[1].split()[0]) for x in log.splitlines() if "silence_start: " in x]
    ends = [float(x.split("silence_end: ")[1].split()[0]) for x in log.splitlines() if "silence_end: " in x]
    end = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(stem)],
                               capture_output=True, text=True).stdout)
    return list(zip(starts, ends + [end] * (len(starts) - len(ends))))


def findings(spans, plan):
    """Args: quiet spans, a timing dict. Output: [(level, start, end, scene id)] for spans that count."""
    spoken = sorted((ln["start"], ln["end"]) for ln in plan["lines"].values())
    if not spoken:
        return []
    first, last = spoken[0][0], spoken[-1][1]
    music = [(s["start"], s["end"]) for s in plan["scenes"] if s.get("music")]
    out = []
    for a, b in spans:
        a, b = max(a, first), min(b, last)
        for m0, m1 in music:
            if m0 <= a < m1:
                a = m1
            if m0 < b <= m1:
                b = m0
        n = b - a
        if n <= WARN:
            continue
        mid = (a + b) / 2
        sc = next((s["id"] for s in plan["scenes"] if s["start"] <= mid < s["end"]), "?")
        out.append(("FAIL" if n > FAIL else "WARN", round(a, 2), round(b, 2), sc))
    return out


def check(base):
    """Args: the film folder. Output: (findings, ok) where ok is False if any span is over FAIL."""
    base = Path(base)
    plan = json.loads((base / "timing.json").read_text())
    found = findings(quiet_spans(base / "out/voiceover/voice-stem.wav"), plan)
    return found, not any(f[0] == "FAIL" for f in found)


def main():
    found, ok = check(sys.argv[1])
    for level, a, b, sc in found:
        print(f"{level} {a:7.2f}-{b:7.2f}s  {b - a:.2f}s without speech  scene {sc}")
    print(f"silence check: {'pass' if ok else 'FAIL'} ({len(found)} span(s) over {WARN}s, limit {FAIL}s)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
