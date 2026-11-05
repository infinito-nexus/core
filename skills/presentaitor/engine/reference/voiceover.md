# Voiceover

One JSON script drives everything: lines with start times, voices, the music bed and the mix. `voiceover.py` speaks every line, checks every take, fits each line into its slot, mixes it over the music and writes a track exactly as long as the film. Scripts are in `$SKILL_DIR/scripts`.

## 0. Choose the engine

Unless the user has already picked one, ask, because it decides the install and the sound:

| | Chatterbox | Kokoro |
|---|---|---|
| Sound | the most natural: intonation, pauses, some emotion | clear and pleasant, a little more even |
| Voices | one built-in voice, or a timbre taken from a 10–20 s sample, so one narrator carries every film | 54 preset voices: American and British English, plus Spanish, French, Hindi, Italian, Japanese, Portuguese and Mandarin |
| Install | about 4 GB (8 GB once a voice uses the Turbo sample) | about 0.6 GB |
| Speed | slow: three takes a line, the best one kept | fast: one take, a second or two a line |

Suggest Chatterbox for a brand narrator that should sound human and stay the same across films, Kokoro for a quick turnaround, a small machine or one of its other languages. Either way, draft the timing with `say` first. The choice is the script's `"backend"`.

## 1. Write the lines

- One idea per line, 4–12 words, in the viewer's language. It names what the screen is showing right then.
- The voice times the film: lines have no start times. Group them into scenes; the picture follows `line(id)` and `scene(id)` from `timing.js`.
- Numbers, currencies and names as they should be said: "four fifty", "twelve dollars", and a name the model misreads spelled the way it sounds.
- Show the lines and their scenes to the user before generating the final voice.

## 2. The script

`voiceover.json` in the film folder (paths are relative to it):

```json
{
  "fps": 60, "bpm": 110,
  "music": "audio/edit.wav",
  "out": "audio/voiceover-mix",
  "backend": "chatterbox",
  "voices": {
    "narrator": {"sample": "turbo", "exaggeration": 0.62, "cfg_weight": 0.35, "say": "Samantha"}
  },
  "scenes": [
    {"id": "intro", "music": 3.0},
    {"id": "spend", "lines": ["n01", "n02"]},
    {"id": "end", "lines": ["n03"], "min": 4}
  ],
  "lines": [
    {"id": "n01", "voice": "narrator", "text": "This is where your money goes."},
    {"id": "n02", "voice": "narrator", "text": "Say it, and it's saved.", "hold": 0.5},
    {"id": "n03", "voice": "narrator", "text": "Next up: budgets that plan themselves."}
  ],
  "mix": {"music_gain": 0.26, "duck_ratio": 2.8, "lufs": -16}
}
```

Layout: lines in a scene are 0.35 s apart, a scene change leaves 0.8 s, scene ends snap to the nearest half beat. `"music": s` is a scene without lines (intro or outro under music). `"hold": s` leaves room after a line, `"min": s` keeps a scene at least that long, `"clip": [from, to]` shows that part of `"footage": {"src": ...}` during the line. `"captions": true|false` overrides the captions default. The run writes `timing.json`, `words.json` and `src/timing.js`, and prints the first scene whose timing changed.

A script without `"scenes"` (a v1 film) keeps its fixed `"start"` times, `"frames"` and `"until"`: the line is sped up by at most 1.2× to finish by then.

A voice can carry settings for every engine, so switching `backend` changes nothing else.

Voice settings (Chatterbox): `sample` is the timbre: `"turbo"` (Chatterbox Turbo's built-in voice, cloned), a path to a clean 10–20 s WAV of a voice the user has rights to, or absent for the original model's own voice. `exaggeration` 0.5–0.7 (higher is livelier), `cfg_weight` 0.3–0.5 (lower is slower and more natural). For a second character use a different `sample`, because `"turbo"` is one voice.

Voice settings (Kokoro): `kokoro` is the voice: `af_heart`, `af_bella`, `am_michael`, `bf_emma`, `bm_george` and the rest: the first letter is the language (a American, b British English, e Spanish, f French, h Hindi, i Italian, j Japanese, p Portuguese, z Mandarin), the second f or m. `speed` 0.85–1.15; `lang` is the espeak-ng language (`en-us` by default, `en-gb` for the British voices).

## 3. Draft with `say`, then speak it for real

```bash
python3 $SKILL_DIR/scripts/voiceover.py voiceover.json --backend say   # seconds, for timing
python3 $SKILL_DIR/scripts/voiceover.py voiceover.json                 # the final, with the script's backend
```

- Chatterbox needs a one-time setup: its own Python 3.11 environment with PyTorch, about 4 GB with the weights (8 GB once a voice uses the Turbo sample), downloaded once. Ask the user first, then `bash $SKILL_DIR/scripts/install.sh chatterbox` (it needs uv; see [setup](setup.md)). An existing environment: `MOTION_DESIGNER_TTS_PYTHON=/path/bin/python`.
- Kokoro needs a smaller one-time setup: its own Python environment with kokoro-onnx and the model files, about 0.6 GB. Ask first, then `bash $SKILL_DIR/scripts/install.sh kokoro`. An existing one: `MOTION_DESIGNER_KOKORO_PYTHON=/path/bin/python`, and `MOTION_DESIGNER_KOKORO_MODELS=/dir` for `kokoro-v1.0.onnx` and `voices-v1.0.bin`.
- Chatterbox speaks each line three times; the take whose intonation moves most like speech is kept (`out/voiceover/chatterbox/takes.json` says why). Kokoro speaks a line the same way every time, so it takes one. Takes are cached in `out/voiceover/<backend>/` with a `.key` of the text and voice settings; a changed line is spoken again on its own (`cache miss`), the rest are reused (`cache hit`). Delete a line's `.wav` to force a new take.
- Every take is trimmed: silence before and after it is removed, and any pause inside it is cut to about 0.5 s (never more than 0.6 s). A fresh take must last 0.8–1.3× a plain reading; Chatterbox speaks a take outside that range again, up to three times, then keeps the last one with a warning. A take must also end before its `until` or the next line, or the run stops with the reason. Reword the line or move it.

## 4. Mix

The mix is built in: a light voice chain (high-pass, presence, compression, de-ess), the music at `music_gain` with a dip at 2.6 kHz, ducked by the voice (`duck_ratio`), then loudness-normalised to `lufs` (−16 LUFS, −1.5 dBTP). The run ends with the balance:

```
voice 17.9 dB above the music while speaking; music between lines -7.0 dB against the voice
```

The music comes back about 0.3 s after the voice stops (sidechain release 300 ms). The voice-only stem is kept as `out/voiceover/voice-stem.wav` for the silence check (`scripts/silence.py <film>`: a warning over 1.2 s without speech, a failure over 2.5 s, music-only scenes and the intro and outro excepted).

Aim for 16–20 dB while speaking and −5 to −9 dB between lines. Too much music: lower `music_gain` by 0.04 or raise `duck_ratio`; music too faint between lines: raise `music_gain`. Tell the user the two numbers when you change them.

## 5. Put it on the picture

No re-render. Mux the mix over the rendered video:

```bash
ffmpeg -y -i out/film.mp4 -i audio/voiceover-mix.m4a -map 0:v -map 1:a -c copy out/film-voiceover.mp4
```

Check with `ffprobe` that the video and audio durations match `frames / fps`.

## Rules

- Chatterbox output carries Resemble's inaudible Perth watermark; say so. Kokoro-82M is released under Apache-2.0. Clone only voices the user has the rights to; never imitate a real person without their consent.
- macOS `say` voices are for drafts: their licence is personal and non-commercial.
- Same music cut as the music-only version, so both versions share one picture.
- More in [rights](rights.md#voices).
