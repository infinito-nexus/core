import argparse
import array
import json
import math
import random
import subprocess
import wave
from pathlib import Path

SR = 44100
NOTES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
         "A": 9, "A#": 10, "Bb": 10, "B": 11}


def pitch(key, degree, octave=5):
    name, _, mode = key.partition(" ")
    scale = [0, 3, 5, 7, 10] if mode.lower().startswith("min") else [0, 2, 4, 7, 9]
    midi = 12 * (octave + 1) + NOTES[name] + scale[degree % 5] + 12 * (degree // 5)
    return 440 * 2 ** ((midi - 69) / 12)


def peak(x, db):
    top = max(abs(v) for v in x) or 1
    g = 10 ** (db / 20) / top
    rise, fall = int(0.0008 * SR), int(0.012 * SR)
    return [v * g * min(1, i / rise, (len(x) - 1 - i) / fall) for i, v in enumerate(x)]


def noise(n, rng):
    return [rng.uniform(-1, 1) for _ in range(n)]


def resonator(x, freqs, q):
    y, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for i, v in enumerate(x):
        w = 2 * math.pi * freqs(i) / SR
        alpha, cos = math.sin(w) / (2 * q), math.cos(w)
        a0 = 1 + alpha
        out = (alpha * v - alpha * x2 + 2 * cos * y1 - (1 - alpha) * y2) / a0
        x2, x1, y2, y1 = x1, v, y1, out
        y.append(out)
    return y


def tick(o, rng):
    n = int(0.02 * SR)
    f = 3800 * (1 + 0.08 * rng.uniform(-1, 1))
    x = [v * math.exp(-i / (0.0025 * SR)) for i, v in enumerate(noise(n, rng))]
    return peak(resonator(x, lambda i: f, 1.2), -30)


def click(o, rng):
    a, b = tick(o, rng), tick(o, rng)
    gap = int(0.028 * SR)
    x = a + [0.0] * (gap + len(b) - len(a))
    for i, v in enumerate(b):
        x[gap + i] += 1.3 * v
    return peak(x, -22)


def pop(o, rng):
    f0, n, ph, x = pitch(o["key"], o.get("note", 4)), int(0.16 * SR), 0.0, []
    for i in range(n):
        t = i / SR
        ph += 2 * math.pi * f0 * (1 + 0.9 * math.exp(-t / 0.012)) / SR
        x.append(math.sin(ph) * (1 - math.exp(-t / 0.001)) * math.exp(-t / 0.045))
    return peak(x, -16)


def thud(o, rng):
    n, ph, x = int(0.28 * SR), 0.0, []
    for i in range(n):
        t = i / SR
        ph += 2 * math.pi * (58 + 80 * math.exp(-t / 0.03)) / SR
        x.append((math.sin(ph) + 0.35 * math.sin(2 * ph)) * (1 - math.exp(-t / 0.002)) * math.exp(-t / 0.07))
    return peak(x, -17)


def sweep(o, rng, seconds, lo, hi, q, db):
    n = int(seconds * SR)
    x = noise(n, rng)
    y = resonator(x, lambda i: lo * (hi / lo) ** (i / n), q)
    return peak([v * math.sin(math.pi * (i / n) ** 0.8) ** 2 for i, v in enumerate(y)], db)


def whoosh(o, rng):
    return sweep(o, rng, 0.5, 350, 2800, 1.4, -22)


def swish(o, rng):
    return sweep(o, rng, 0.28, 1800, 7000, 1.8, -30)


def blip(o, rng):
    f, n, x = pitch(o["key"], o.get("note", 0)), int(0.2 * SR), []
    for i in range(n):
        t = i / SR
        mod = 2.2 * math.exp(-t / 0.02) * math.sin(2 * math.pi * 3.5 * f * t)
        x.append(math.sin(2 * math.pi * f * t + mod) * (1 - math.exp(-t / 0.0015)) * math.exp(-t / 0.07))
    return peak(x, -19)


def chime(o, rng):
    f0, n = pitch(o["key"], o.get("note", 0)), int(2.2 * SR)
    partials = [(1, 1, 1.4), (2.0, 0.45, 0.9), (3.0, 0.25, 0.6), (4.16, 0.12, 0.4), (5.43, 0.08, 0.3), (2.997, 0.2, 0.8)]
    x = [sum(a * math.sin(2 * math.pi * f0 * r * i / SR) * math.exp(-i / (d * SR)) for r, a, d in partials) * (1 - math.exp(-i / (0.003 * SR)))
         for i in range(n)]
    return peak(x, -13)


def hop(o, rng):
    n, ph, x = int(0.26 * SR), 0.0, []
    for i in range(n):
        t = i / SR
        f = (260 + 360 * min(1, t / 0.12) - 200 * max(0, (t - 0.12) / 0.14)) * (1 + 0.03 * math.sin(2 * math.pi * 14 * t))
        ph += 2 * math.pi * f / SR
        x.append(math.sin(ph) * min(1, t / 0.005) * min(1, (0.26 - t) / 0.06))
    return peak(x, -23)


SOUNDS = {"tick": tick, "click": click, "pop": pop, "thud": thud, "whoosh": whoosh, "swish": swish, "blip": blip, "chime": chime, "hop": hop}


def lufs(path):
    out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(out.rsplit("I:", 1)[1].split("LUFS")[0])


def write(path, left, right):
    pcm = array.array("h", (max(-32767, min(32767, int(v * 32767))) for pair in zip(left, right) for v in pair))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cues")
    ap.add_argument("--key", default="C major")
    ap.add_argument("--music")
    ap.add_argument("--music-gain", type=float, default=0.32)
    ap.add_argument("--lufs", type=float, default=-16)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    film = json.loads(Path(a.cues).read_text())
    length = film["frames"] / film["fps"]
    n = round(length * SR)
    left, right = [0.0] * n, [0.0] * n
    counts = {}
    for k, cue in enumerate(film["cues"]):
        make = SOUNDS.get(cue["sound"])
        if not make:
            raise SystemExit(f"no sound {cue['sound']!r}; there are {', '.join(SOUNDS)}")
        x = make({"key": a.key, **cue}, random.Random(k))
        g = 10 ** (cue.get("gain", 0) / 20)
        pan = max(-1.0, min(1.0, cue.get("pan", 0)))
        gl, gr = g * math.cos((pan + 1) * math.pi / 4) * math.sqrt(2), g * math.sin((pan + 1) * math.pi / 4) * math.sqrt(2)
        at = round(cue["t"] * SR)
        for i, v in enumerate(x):
            j = (at + i) % n
            left[j] += gl * v
            right[j] += gr * v
        counts[cue["sound"]] = counts.get(cue["sound"], 0) + 1
    stem = Path(a.out + "-sfx.wav")
    write(stem, left, right)
    print(f"{len(film['cues'])} cues over {length:.3f}s: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())) + f": {stem}")
    if a.music:
        raw = Path(a.out + "-raw.wav")
        graph = (f"[0:a]aresample={SR},volume={a.music_gain},equalizer=f=3500:t=q:w=1.2:g=-4[bed];"
                 f"[bed][1:a]amix=inputs=2:normalize=0,apad=whole_dur={length:.6f},atrim=end_sample={n}")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.music, "-i", str(stem), "-filter_complex", graph,
                        "-ac", "2", "-c:a", "pcm_f32le", str(raw)], check=True)
        gain = a.lufs - lufs(raw)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af",
                        f"volume={gain:.2f}dB,alimiter=limit=0.84:attack=5:release=60:level=false:latency=1,apad=whole_dur={length:.6f},atrim=end_sample={n}",
                        "-c:a", "pcm_s16le", a.out + ".wav"], check=True)
        raw.unlink()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.out + ".wav", "-c:a", "aac", "-b:a", "256k", a.out + ".m4a"], check=True)
        print(a.out + ".wav", a.out + ".m4a")


if __name__ == "__main__":
    main()
