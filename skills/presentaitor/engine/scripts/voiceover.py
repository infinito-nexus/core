import argparse
import array
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import timing

HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("MOTION_DESIGNER_HOME", Path.home() / ".cache/motion-designer"))
TTS_PYTHON = Path(os.environ.get("MOTION_DESIGNER_TTS_PYTHON", HOME / "chatterbox/bin/python"))
KOKORO_PYTHON = Path(os.environ.get("MOTION_DESIGNER_KOKORO_PYTHON", HOME / "kokoro/bin/python"))
SILENCE = "-40dB"
MAX_PAUSE = 0.6
TRIM = f"silenceremove=start_periods=1:start_threshold={SILENCE}:start_duration=0.05:start_silence=0.03"
# ffmpeg 6.1 ignores stop_silence when stop_periods is negative: a pause is cut to about stop_duration.
CAP = f"silenceremove=stop_periods=-1:stop_threshold={SILENCE}:stop_duration={MAX_PAUSE - 0.1}"
FIT = (0.8, 1.3)
RETRIES = 3
WORDS_PER_SECOND = 3.0
VOICE_FX = ("highpass=f=85,equalizer=f=280:t=q:w=1.1:g=-2.5,equalizer=f=3300:t=q:w=1.3:g=2.5,"
            "equalizer=f=9500:t=q:w=1:g=1.5,acompressor=threshold=-22dB:ratio=3:attack=6:release=140:makeup=3,deesser=i=0.35")


def run(*args):
    return subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)


def duration(path):
    return float(run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path).stdout)


def trimmed(src, dst):
    run("ffmpeg", "-v", "error", "-y", "-i", src, "-af", f"{TRIM},{CAP},areverse,{TRIM},areverse,aresample=44100", "-ac", "2", dst)
    return dst


def samples(path, sr=8000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    x = array.array("f")
    x.frombytes(raw)
    return x


def silences(path, threshold=SILENCE, least=0.05):
    log = subprocess.run(["ffmpeg", "-i", str(path), "-af", f"silencedetect=n={threshold}:d={least}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(ln.split("silence_start: ")[1].split()[0]) for ln in log.splitlines() if "silence_start: " in ln]
    ends = [float(ln.split("silence_end: ")[1].split()[0]) for ln in log.splitlines() if "silence_end: " in ln]
    return list(zip(starts, ends + [duration(path)] * (len(starts) - len(ends))))


def longest_gap(path):
    end = duration(path)
    inner = [b - a for a, b in silences(path) if a > 0.05 and b < end - 0.05]
    return max(inner, default=0.0)


def word_times(take, text, start):
    """Estimate when each word is spoken in a trimmed take.

    Args:
        take: the trimmed WAV of one line.
        text: the line's text.
        start: the line's start in the film, seconds.

    Output:
        [{"w", "t0", "t1"}] in film seconds. Pauses found in the take are skipped; the speech
        between them is shared out by word length (characters plus one), which tracks syllables.
    """
    end = duration(take)
    quiet = [(a, b) for a, b in silences(take, least=0.08) if a > 0.02 and b < end - 0.02]
    talk, cur = [], 0.0
    for a, b in quiet:
        talk.append((cur, a))
        cur = b
    talk.append((cur, end))
    words = text.split()
    weights = [len(w.strip(".,:;!?\"'")) + 1 for w in words]
    total, spoken = sum(weights), sum(b - a for a, b in talk)

    def at(f):
        left = f * spoken
        for a, b in talk:
            if left <= b - a + 1e-9:
                return a + left
            left -= b - a
        return end

    times, acc = [], 0
    for k in weights:
        times.append([at(acc / total), at((acc + k) / total)])
        acc += k
    for a, b in quiet:
        i = min(range(len(times) - 1), key=lambda j: abs(times[j][1] - a), default=None)
        if i is not None and abs(times[i][1] - a) < 0.4:
            times[i][1], times[i + 1][0] = a, b
    return [{"w": w, "t0": round(start + t0, 3), "t1": round(start + max(t1, t0 + 0.05), 3)} for w, (t0, t1) in zip(words, times)]


def level_db(path, windows, sr=8000):
    x = samples(path, sr)
    acc = n = 0
    for a, b in windows:
        seg = x[int(a * sr):int(b * sr)]
        acc += sum(v * v for v in seg)
        n += len(seg)
    return 10 * math.log10(acc / max(n, 1) + 1e-12)


def plain_length(text, tmp, key, wps=WORDS_PER_SECOND):
    if not shutil.which("say"):
        return len(text.split()) / wps
    run("say", "-r", "172", "-o", tmp / f"{key}.plain.aiff", text)
    return duration(trimmed(tmp / f"{key}.plain.aiff", tmp / f"{key}.plain.wav"))


def speak(spec, backend, cache, tmp, attempt=0):
    cache.mkdir(parents=True, exist_ok=True)
    todo = [ln for ln in spec["lines"] if not (cache / f"{ln['id']}.wav").exists()]
    if backend == "say":
        for ln in todo:
            v = spec["voices"].get(ln["voice"], {})
            run("say", "-v", v.get("say", "Samantha"), "-r", str(v.get("rate", 172)), "-o", tmp / f"{ln['id']}.aiff", ln["text"])
            run("ffmpeg", "-v", "error", "-y", "-i", tmp / f"{ln['id']}.aiff", cache / f"{ln['id']}.wav")
        return todo
    if not todo:
        return todo
    jobs = [{**ln, "settings": spec["voices"].get(ln["voice"], {}), "plain": ln["plain"], "attempt": attempt, "fit": FIT}
            for ln in todo]
    (tmp / "lines.json").write_text(json.dumps(jobs))
    if backend == "kokoro":
        if not KOKORO_PYTHON.exists():
            raise SystemExit(f"Kokoro is not set up at {KOKORO_PYTHON}. Ask the user, then run: bash {HERE / 'install.sh'} kokoro "
                             f"(a local Python environment, about 0.6 GB). Or draft with --backend say.")
        subprocess.run([str(KOKORO_PYTHON), str(HERE / "tts_kokoro.py"), str(tmp / "lines.json"), str(cache)], check=True)
        return todo
    if not TTS_PYTHON.exists():
        raise SystemExit(f"Chatterbox is not set up at {TTS_PYTHON}. Ask the user, then run: bash {HERE / 'install.sh'} chatterbox "
                         f"(a local Python environment, about 4 GB), or choose --backend kokoro. Or draft with --backend say.")
    subprocess.run([str(TTS_PYTHON), str(HERE / "tts_chatterbox.py"), str(tmp / "lines.json"), str(cache)], check=True)
    return todo


def refresh_cache(spec, lines, backend, cache):
    """Drop cached takes whose text or voice settings changed; log a hit or a miss per line.

    Args:
        spec, backend, cache: as for speak().
        lines: the script's lines.

    Output:
        {line id: take key}; write_keys() stores them once the takes exist.
    """
    keys = {}
    for ln in lines:
        key = timing.take_key(ln, spec["voices"].get(ln["voice"], {}), backend)
        keys[ln["id"]] = key
        wav, stamp = cache / f"{ln['id']}.wav", cache / f"{ln['id']}.key"
        if wav.exists() and (not stamp.exists() or stamp.read_text().strip() == key):
            print(f"cache hit   {ln['id']}")
            continue
        if wav.exists():
            wav.unlink()
        print(f"cache miss  {ln['id']}  {ln['text']}")
    return keys


def write_keys(keys, cache):
    for lid, key in keys.items():
        if (cache / f"{lid}.wav").exists():
            (cache / f"{lid}.key").write_text(key + "\n")


def fit_takes(spec, lines, backend, cache, tmp):
    """Regenerate fresh takes whose trimmed length is outside FIT times the plain reading.

    Args:
        spec, backend, cache, tmp: as for speak().
        lines: lines with "plain" set; only those without a cached take are spoken and checked.

    Output:
        ids of fresh takes still outside FIT after RETRIES attempts (kept, with a warning).
    """
    fresh = speak({**spec, "lines": lines}, backend, cache, tmp)
    for attempt in range(1, RETRIES + 1):
        bad = []
        for ln in fresh:
            ratio = duration(trimmed(cache / f"{ln['id']}.wav", tmp / f"{ln['id']}.fit.wav")) / ln["plain"]
            if not FIT[0] <= ratio <= FIT[1]:
                bad.append(ln)
                print(f"{ln['id']}: take is {ratio:.2f}x the plain reading, outside {FIT[0]}-{FIT[1]}x")
        if not bad or backend != "chatterbox" or attempt == RETRIES:
            return [ln["id"] for ln in bad]
        for ln in bad:
            (cache / f"{ln['id']}.wav").unlink()
        fresh = speak({**spec, "lines": bad}, backend, cache, tmp, attempt)
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--backend")
    a = ap.parse_args()
    path = Path(a.script).resolve()
    spec = json.loads(path.read_text())
    base = path.parent
    backend = a.backend or spec.get("backend", "chatterbox")
    fps = spec.get("fps", 60)
    mix = {"music_gain": 0.26, "duck_ratio": 2.8, "lufs": -16, **spec.get("mix", {})}
    cache = base / "out/voiceover" / backend
    for v in spec.get("voices", {}).values():
        if v.get("sample") not in (None, "turbo"):
            v["sample"] = str((base / v["sample"]).resolve())

    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        lines = spec["lines"]
        for ln in lines:
            wps = spec["voices"].get(ln["voice"], {}).get("wps", WORDS_PER_SECOND)
            ln["plain"] = plain_length(ln["text"], tmp, ln["id"], wps)
        keys = refresh_cache(spec, lines, backend, cache)
        for lid in fit_takes(spec, lines, backend, cache, tmp):
            tries = f"after {RETRIES} attempts" if backend == "chatterbox" else f"({backend} speaks a line the same way every time)"
            print(f"WARNING {lid}: no take within {FIT[0]}-{FIT[1]}x {tries}; kept the last take, reword the line if it sounds off")
        write_keys(keys, cache)

        if "scenes" in spec:
            durs = {ln["id"]: duration(trimmed(cache / f"{ln['id']}.wav", tmp / f"{ln['id']}.wav")) for ln in lines}
            plan = timing.layout(spec["scenes"], {ln["id"]: ln for ln in lines}, durs, spec["bpm"], fps)
            plan["words"] = {ln["id"]: word_times(tmp / f"{ln['id']}.wav", ln["text"], plan["lines"][ln["id"]]["start"]) for ln in lines}
            plan["captions"] = spec.get("captions", os.environ.get("PRESENTAITOR_CAPTIONS") == "1")
            (base / "words.json").write_text(json.dumps(plan["words"], indent=1) + "\n")
            changed = timing.write(plan, base, spec.get("src", "src"))
            print(f"timing.json: {plan['duration']:.2f}s, {plan['frames']} frames; "
                  + (f"timing changed from scene {changed}" if changed else "timing unchanged"))
            for ln in lines:
                ln["start"] = plan["lines"][ln["id"]]["start"]
            length = plan["duration"]
        else:
            print("no \"scenes\" in the script: fixed start times (a v1 film); add scenes to time it by the voice")
            length = spec["frames"] / fps
        lines = sorted(lines, key=lambda ln: ln["start"])

        clips, speech = [], []
        for ln, nxt in zip(lines, [ln["start"] for ln in lines[1:]] + [length]):
            clip = trimmed(cache / f"{ln['id']}.wav", tmp / f"{ln['id']}.wav")
            got = duration(clip)
            gap = longest_gap(clip)
            assert gap <= MAX_PAUSE, f"{ln['id']} {ln['text']!r}: a {gap:.2f}s gap inside the take survived the {MAX_PAUSE}s cap"
            limit = ln.get("until", nxt - 0.05)
            if ln.get("until") and ln["start"] + got > limit:
                tempo = got / (limit - ln["start"])
                assert tempo <= 1.2, f"{ln['id']} {ln['text']!r}: {got:.2f}s cannot fit before {limit:.2f}s"
                clip = tmp / f"{ln['id']}.fit.wav"
                run("ffmpeg", "-v", "error", "-y", "-i", tmp / f"{ln['id']}.wav", "-af", f"atempo={tempo:.4f}", clip)
                got = duration(clip)
            assert ln["start"] + got <= limit + 0.1, f"{ln['id']} {ln['text']!r} ends at {ln['start'] + got:.2f}s, past {limit:.2f}s"
            print(f"{ln['start']:6.2f}–{ln['start'] + got:6.2f}s  {ln['voice']:9s} {ln['text']}")
            clips.append((ln["start"], clip))
            speech.append((ln["start"], ln["start"] + got))

        if not clips:
            raise SystemExit("the script has no spoken lines; a film without a voice needs no voiceover.py run")
        bed = duration(base / spec["music"])
        if bed < length - 0.05:
            print(f"WARNING the music ({bed:.2f}s) is shorter than the film ({length:.2f}s); "
                  f"cut a longer edit with music_edit.py (--bars {math.ceil(length / (240 / spec.get('bpm', 120)))} or more)")
        inputs, chains = [], []
        for i, (start, clip) in enumerate(clips):
            inputs += ["-i", str(clip)]
            ms = round(start * 1000)
            chains.append(f"[{i}:a]adelay={ms}|{ms}[v{i}]")
        n = len(clips)
        out = base / spec["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        graph = (";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(n)) +
                 f"amix=inputs={n}:normalize=0,{VOICE_FX},apad,atrim=0:{length:.6f},asplit=3[vo][key][vstem];"
                 f"[{n}:a]volume={mix['music_gain']},equalizer=f=2600:t=q:w=1.4:g=-5"
                 + (f",afade=t=out:st={max(0.0, length - 2):.3f}:d=2" if "scenes" in spec else "") + "[bed];"
                 f"[bed][key]sidechaincompress=threshold=0.012:ratio={mix['duck_ratio']}:attack=20:release=300:knee=6,asplit[ducked][mstem];"
                 f"[ducked][vo]amix=inputs=2:normalize=0,loudnorm=I={mix['lufs']}:TP=-1.5:LRA=11,aresample=44100,"
                 f"apad=whole_dur={length:.6f},atrim=end_sample={round(length * 44100)}[out]")
        run("ffmpeg", "-v", "error", "-y", *inputs, "-i", base / spec["music"], "-filter_complex", graph,
            "-map", "[out]", "-ar", "44100", "-c:a", "pcm_s16le", f"{out}.wav",
            "-map", "[vstem]", "-c:a", "pcm_s16le", tmp / "voice.wav",
            "-map", "[mstem]", "-c:a", "pcm_s16le", tmp / "music.wav")
        run("ffmpeg", "-v", "error", "-y", "-i", f"{out}.wav", "-c:a", "aac", "-b:a", "256k", f"{out}.m4a")
        shutil.copy(tmp / "voice.wav", cache.parent / "voice-stem.wav")

        v = level_db(tmp / "voice.wav", speech)
        edges = [0.0] + [x for seg in speech for x in seg] + [length]
        gaps = [(p, q) for p, q in zip(edges[::2], edges[1::2]) if q - p > 1.0]
        between = f"{level_db(tmp / 'music.wav', gaps) - v:.1f} dB against the voice" if gaps else "n/a (no gap over 1 s)"
        print(f"voice {v - level_db(tmp / 'music.wav', speech):.1f} dB above the music while speaking; music between lines {between}")
        print(f"{out}.wav {duration(f'{out}.wav'):.3f}s, {out}.m4a")


if __name__ == "__main__":
    main()
