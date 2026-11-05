import argparse
import array
import json
import math
import subprocess

SR = 11025
HOP = 64


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    x = array.array("f")
    x.frombytes(raw)
    return x


def onset_envelope(x):
    env, prev_sample, prev_log = [], 0.0, 0.0
    for i in range(0, len(x) - HOP, HOP):
        e = 0.0
        for v in x[i:i + HOP]:
            d = v - prev_sample
            prev_sample = v
            e += d * d
        lg = math.log(1e-9 + e)
        env.append(max(0.0, lg - prev_log))
        prev_log = lg
    mean = sum(env) / len(env)
    return [v - mean for v in env]


def grid_score(env, period, phase):
    total, n, t = 0.0, 0, phase
    last = len(env) - 2
    while t < last:
        i = int(t)
        total += env[i] + (env[i + 1] - env[i]) * (t - i)
        n += 1
        t += period
    return total / max(n, 1)


def smooth(env, w=3):
    out, acc = [], sum(env[:w])
    for i in range(len(env)):
        if i + w < len(env):
            acc += env[i + w]
        if i - w - 1 >= 0:
            acc -= env[i - w - 1]
        out.append(acc / (min(len(env), i + w + 1) - max(0, i - w)))
    return out


def tempo(env, lo=70, hi=180):
    fps = SR / HOP

    def acf(lag):
        k, n = int(round(lag)), len(env) - int(round(lag))
        return sum(env[i] * env[i + k] for i in range(0, n, 2)) / (n / 2)

    bpm = max(range(lo * 10, hi * 10 + 1, 5),
              key=lambda t: acf(60 * fps / (t / 10)) * math.exp(-0.5 * math.log2(t / 1200) ** 2)) / 10
    sm = smooth(env)

    def placed(b, steps):
        period = 60 * fps / b
        return max((grid_score(sm, period, p), p) for p in frange(0, period, period / steps))

    for step, reach in ((0.05, 40), (0.005, 10), (0.0005, 10)):
        bpm = max((bpm + k * step for k in range(-reach, reach + 1)), key=lambda b: placed(b, 48)[0])
    return bpm, placed(bpm, 128)[1] / fps


def fit(env, bpm, beat0):
    fps = SR / HOP
    period, near = 60 / bpm, round(0.04 * fps)
    hits = []
    for i in range(int((len(env) / fps - beat0) / period) + 1):
        c = round((beat0 + i * period) * fps)
        lo, hi = max(1, c - near), min(len(env) - 2, c + near)
        if lo < hi:
            j = max(range(lo, hi + 1), key=lambda k: env[k])
            a, b, c = env[j - 1], env[j], env[j + 1]
            curve = a - 2 * b + c
            hits.append((i, (j + 0.5 + (0.5 * (a - c) / curve if curve else 0.0)) / fps, b))
    floor = sorted(h[2] for h in hits)[len(hits) // 4]
    points = [(i, t) for i, t, strength in hits if strength >= floor]

    def line(pts):
        mi, mt = sum(i for i, _ in pts) / len(pts), sum(t for _, t in pts) / len(pts)
        slope = sum((i - mi) * (t - mt) for i, t in pts) / sum((i - mi) ** 2 for i, _ in pts)
        return slope, mt - slope * mi

    slope, start = line(points)
    slope, start = line([(i, t) for i, t in points if abs(t - start - slope * i) < 0.012])
    return 60 / slope, start % slope


def frange(a, b, step):
    v = a
    while v < b:
        yield v
        v += step


def rms(x, a, b):
    seg = x[max(0, int(a * SR)):int(b * SR)]
    return math.sqrt(sum(v * v for v in seg) / max(len(seg), 1))


def spectral(path):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-af",
                          "aformat=channel_layouts=mono,aresample=22050,aspectralstats=win_size=2048:overlap=0.5:measure=centroid+flatness,"
                          "ametadata=print:file=-", "-f", "null", "-"], check=True, capture_output=True, text=True).stdout
    frames = []
    for line in out.splitlines():
        if line.startswith("frame:"):
            frames.append([float(line.rsplit("pts_time:", 1)[1]), math.nan, math.nan])
        elif ".centroid=" in line:
            frames[-1][1] = float(line.split("=")[1])
        elif ".flatness=" in line:
            frames[-1][2] = float(line.split("=")[1])
    return [f for f in frames if f[1] == f[1] and f[2] == f[2]]


def attacks(env):
    fps = SR / HOP
    peaks = [i for i in range(1, len(env) - 1) if env[i] > 0 and env[i] >= env[i - 1] and env[i] > env[i + 1]]
    if not peaks:
        return []
    strong = sorted(env[i] for i in peaks)[int(0.95 * (len(peaks) - 1))]
    out = []
    for i in peaks:
        if env[i] >= 0.35 * strong and (not out or i / fps - out[-1] >= 0.05):
            out.append(i / fps)
    return out


def sound(x, env, path, bars, bar_len, beats_per_bar):
    frames, hits = spectral(path), attacks(env)
    for b in bars:
        a, z = b["start"], b["start"] + bar_len
        weighted = [(c, f, rms(x, t, t + 0.093)) for t, c, f in frames if a <= t < z]
        total = sum(w for _, _, w in weighted) or 1
        peak = max((abs(v) for v in x[int(a * SR):int(z * SR)]), default=0)
        b["hits"] = round(sum(a <= h < z for h in hits) / beats_per_bar, 2)
        b["bright"] = round(sum(c * w for c, _, w in weighted) / total)
        b["fill"] = round(sum(f * w for _, f, w in weighted) / total, 3)
        b["crest"] = round(20 * math.log10(peak / b["rms"]), 1) if b["rms"] and peak else 0


def summary(bars, bpm):
    playing = [b for b in bars if b["rms"] > 0.1 * max(c["rms"] for c in bars)]
    mid = lambda k: sorted(b[k] for b in playing)[len(playing) // 2]
    hits, bright, fill, crest = mid("hits") * bpm / 60, mid("bright"), mid("fill"), mid("crest")
    busy = "busy" if hits > 5 else "steady" if hits > 2.5 else "sparse"
    tone = "bright" if bright > 2500 else "warm" if bright > 1400 else "dark"
    room = "a wall" if fill > 0.3 else "open" if fill > 0.2 else "airy"
    punch = "squashed" if crest < 12 else "even" if crest < 15 else "punchy"
    role = "a bed that leaves room for words and sounds" if fill <= 0.3 and hits <= 5.5 and crest >= 12 else "a lead that fills the frame"
    return (f"sound: {hits:.1f} attacks a second, {bright / 1000:.1f} kHz, fill {fill:.0%}, crest {crest:.0f} dB; "
            f"{busy}, {tone}, {room}, {punch}: {role}")


def draw_sheet(path, out, bars, bar_len):
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                                    check=True, capture_output=True, text=True).stdout)
    w, h = 1600, 480
    boxes = []
    for b in bars:
        x = round(b["start"] / duration * w)
        first = b["bar"] % 4 == 1
        boxes.append(f"drawbox=x={x}:y=0:w={2 if first else 1}:h={h}:color=white@{0.7 if first else 0.3}:t=fill")
        if b["mark"]:
            boxes.append(f"drawbox=x={x}:y=0:w={round(bar_len / duration * w)}:h=10:color={'0x3DDC84' if b['mark'] == 'drop' else '0xFF5A5A'}:t=fill")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-lavfi",
                    f"showspectrumpic=s={w}x{h}:legend=0:mode=combined:color=intensity:scale=log:fscale=log:start=40:stop=16000,{','.join(boxes)}",
                    out], check=True)


def bar_table(x, bpm, beat0, beats_per_bar):
    beat = 60 / bpm
    bar_len = beat * beats_per_bar
    level = [math.log(rms(x, beat0 + (i - 0.1) * beat, beat0 + (i + 0.9) * beat) + 1e-6)
             for i in range(int((len(x) / SR - beat0) / beat))]
    playing = [i for i, v in enumerate(level) if v > max(level) - 4.6]
    lo, hi = playing[0], playing[-1] + 1

    def sharpness(k):
        starts = range(lo + (k - lo) % beats_per_bar, hi - beats_per_bar + 1, beats_per_bar)
        bars = [sum(level[j:j + beats_per_bar]) / beats_per_bar for j in starts]
        return sum((q - p) ** 2 for p, q in zip(bars, bars[1:]))

    score = [sharpness(k) for k in range(beats_per_bar)]
    down = max(range(beats_per_bar), key=lambda k: score[k])
    runner_up = max(v for k, v in enumerate(score) if k != down)
    margin = score[down] / runner_up - 1 if runner_up else 1.0
    first = (beat0 + down * beat) % bar_len
    bars, t = [], first
    while t + bar_len <= len(x) / SR + 1e-6:
        bars.append({"bar": len(bars) + 1, "start": round(t, 3), "rms": round(rms(x, t, t + bar_len), 4)})
        t += bar_len
    kinds = []
    for i, b in enumerate(bars):
        before = [c["rms"] for c in bars[max(0, i - 4):i]]
        ref = sum(before) / len(before) if before else b["rms"]
        b["change"] = round(b["rms"] / ref - 1, 3) if ref else 0
        kinds.append("drop" if b["change"] > 0.3 else "breakdown" if b["change"] < -0.3 else "")
        b["mark"] = "" if i and kinds[i - 1] == kinds[i] else kinds[i]
    return first, bars, margin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--beats-per-bar", type=int, default=4)
    ap.add_argument("--json")
    ap.add_argument("--sheet")
    a = ap.parse_args()
    x = decode(a.track)
    env = onset_envelope(x)
    bpm, beat0 = fit(env, *fit(env, *tempo(env)))
    bar1, bars, margin = bar_table(x, bpm, beat0, a.beats_per_bar)
    bar_len = a.beats_per_bar * 60 / bpm
    sound(x, env, a.track, bars, bar_len, a.beats_per_bar)
    print(f"{bpm:.3f} BPM, beat {60 / bpm:.4f} s, bar {a.beats_per_bar * 60 / bpm:.4f} s, bar 1 starts at {bar1:.3f} s")
    print(f"downbeat {'clear' if margin >= 0.1 else 'uncertain: check that sections start on bar lines in the table'} "
          f"(bars from this beat change {margin:+.0%} more sharply than from any other)")
    peak = max(b["rms"] for b in bars) or 1
    print(f"{'':19}{'loudness':41}{'':11}hits  bright  fill  crest")
    for b in bars:
        print(f"bar {b['bar']:3d}  {b['start']:7.2f}s  {'#' * round(40 * b['rms'] / peak):40s} {b['mark']:9s}"
              f"  {b['hits']:4.2f}  {b['bright'] / 1000:5.1f}k  {b['fill']:4.0%}  {b['crest']:3.0f} dB")
    print(summary(bars, bpm))
    if a.sheet:
        draw_sheet(a.track, a.sheet, bars, bar_len)
        print(a.sheet)
    if a.json:
        with open(a.json, "w") as f:
            json.dump({"bpm": bpm, "beats_per_bar": a.beats_per_bar, "bar1": bar1, "downbeat_margin": round(margin, 3), "bars": bars}, f, indent=1)


if __name__ == "__main__":
    main()
