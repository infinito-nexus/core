import argparse
import json
import subprocess


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("grid")
    ap.add_argument("--from-bar", type=int, required=True)
    ap.add_argument("--bars", type=int, required=True)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    g = json.load(open(a.grid))
    beat = 60 / g["bpm"]
    bar_len = beat * g["beats_per_bar"]
    start = g["bar1"] + (a.from_bar - 1) * bar_len
    frames = round(a.bars * bar_len * a.fps)
    length = frames / a.fps
    assert start >= 0, f"bar {a.from_bar} starts before the track does"
    last = max(b["bar"] for b in g["bars"])
    assert a.from_bar + a.bars - 1 <= last, f"the track has {last} whole bars; bars {a.from_bar}–{a.from_bar + a.bars - 1} run past it"

    af = (f"aresample=44100,apad,atrim=end_sample={round(length * 44100)},"
          f"afade=t=in:d=0.006,afade=t=out:st={length - 0.012:.6f}:d=0.012")
    wav, m4a = a.out + ".wav", a.out + ".m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.6f}", "-t", f"{length + 0.1:.6f}", "-i", a.track,
                    "-af", af, "-ac", "2", "-c:a", "pcm_s16le", wav], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-c:a", "aac", "-b:a", "256k", m4a], check=True)

    beats = a.bars * g["beats_per_bar"]
    print(f"bars {a.from_bar}–{a.from_bar + a.bars - 1}: {start:.4f}s → {start + length:.4f}s, "
          f"{beats} beats at {g['bpm']:.3f} BPM = {frames} frames ({length:.4f}s at {a.fps} fps)")
    print(f"film: BEATS {beats}, DURATION {frames} / {a.fps}, beat n at (n - 1) * {beat:.6f}s")
    for b in g["bars"]:
        if b.get("mark") and a.from_bar <= b["bar"] < a.from_bar + a.bars:
            film_beat = (b["bar"] - a.from_bar) * g["beats_per_bar"] + 1
            print(f"  track bar {b['bar']} ({b['mark']}) → film beat {film_beat} at {(film_beat - 1) * beat:.3f}s")
    print(wav, m4a)


if __name__ == "__main__":
    main()
