# Music and sound

The film's clock is the music's: every action sits on a beat, the biggest reveal on the drop, and the edit is a whole number of bars so it starts on a downbeat and loops. Scripts are in `$SKILL_DIR/scripts`; they need `ffmpeg` and Python 3.

## 0. The sound brief

Decide what the film should sound like before choosing or making a track, and put it in the plan-mode brief (a sentence or two in `<direction>`). A track can be well made and still wrong for the film: a full club groove under typed headlines buries them.

- **The music's role comes from the film type** ([types](types.md)). In a product film the music leads: a groove at 110–128 BPM, a build, the drop on the reveal. In a story, feature cards or a type-led film the words and the interface lead: the music is a bed (few instruments, no lead melody over the text, lots of space, mixed low), each action on screen makes a small sound ([sounds for the actions](#5-sounds-for-the-actions)), and a narrator, if there is one, sits on top. A sting is one hit and its tail.
- **Tempo from the pace.** The beat is the gap between the film's actions, the bar is a scene's step. Calm, friendly or editorial brands sit at 90–110 BPM; energetic launches at 118–128. The film follows the music (`film({ BPM })` from the cut), so pick the tempo for the feel and let the film re-time.
- **An energy map.** One level per scene: the hook sparse, the reveal lifting, the features steady, the end card calm with one warm hit. Choose a take whose breaks and lifts can be lined up with it ([choose the bars](#3-choose-the-bars)).
- **Texture from the look.** Warm paper, serif accents and a friendly character: acoustic and soft electric sounds (nylon guitar, Rhodes, felt piano, soft brushed or lo-fi drums). Dark, neon or technical: synths, a tighter kick. Bold and loud brands: punchy pop or house. Never generic epic or festival EDM for a calm brand.
- **A reference.** When the user shows a film or a track they like, hear it first (`music_gen.py --hear`, and `beats.py` with its sheet) and take its tempo, texture and role in words, never its melody or its audio.

For example: "A quiet lo-fi bed at 105 BPM, nylon guitar or Rhodes over soft drums, under interface sounds on every action; the drums drop out under the hook's last line and come back on the reveal; a chime on the logo."

## 1. Source

- Use the user's track. Without one, make an original for the film ([make one](#make-one)) when ACE-Step is set up (`doctor.sh` lists `acestep`), and say so in the brief; otherwise offer to set it up, or (with the user's go-ahead) search music libraries whose licence covers the planned use ([sources](music-sources.md), [rights](rights.md#music)), offering 3–4 candidates with tempo, mood, licence and a link. Downloading a track needs their yes.
- The music can come last: build the film at the tempo you expect (120–128 BPM) and cut the music to it later; only `BPM` changes.
- Keep the original untouched in `audio/source/` and write `audio/SOURCE.md` (title, artist, URL, licence, date, bars used).
- For a product film: 110–135 BPM, a clear pulse, an intro or build of 8–16 bars, a drop. For the other types: the bed the sound brief describes. No vocals under a voiceover.

### Make one

An original instrumental made for this film with ACE-Step 1.5 (MIT, code and weights) from a caption and a seed. Write `music.json` beside the film, with a few takes in different textures that all fit the sound brief:

```json
{
  "bpm": 104, "key": "D major", "seconds": 64,
  "takes": {
    "rhodes": {"seed": 17, "caption": "A calm, sunny lo-fi instrumental with warm Rhodes electric piano chords, a dusty laid-back hip-hop beat, soft vinyl texture and a mellow round bass. Minimal and uncluttered, a relaxed background for a friendly product video. No vocals."},
    "guitar": {"seed": 5, "caption": "A lighthearted, minimal instrumental built on a warm nylon-string acoustic guitar figure and a soft, laid-back lo-fi hip-hop drum beat with a muted kick and a gentle rimshot. Sparse, with plenty of space, like background music for a friendly app explainer. No vocals."}
  }
}
```

```bash
python3 $SKILL_DIR/scripts/music_gen.py music.json --plan-only     # plans every take and says how each will sound
python3 $SKILL_DIR/scripts/music_gen.py music.json rhodes          # renders the ones that fit: audio/source/ace-rhodes.wav
```

- **Plan, hear, then render.** ACE-Step's language model plans a take in about 20 seconds and then describes its own plan: genre, drums, instruments, mood, tempo and key. That line is the first check against the sound brief. Plans drift from their captions (a nylon-guitar bed planned as dark EBM, a marimba bed as four-on-the-floor house): drop those and render only the takes that fit, since rendering is the slow part.
- **Captions** read the way ACE-Step describes music, in full sentences: the feel and genre, the drums, three or four instruments, the space, what it is for, "No vocals." For a bed leave out "build-up", "drop", "riser" and "euphoric": they pull the plan toward club music. Name moods and instruments, never artists or songs.
- `bpm` is the film's tempo; `seconds` is the film plus 16–32 bars, to cut from. `sections` (default intro, verse, chorus, verse, chorus, outro) sets the order of the parts.
- `music_gen.py --hear <audio> ...` describes any track the same way: a rendered take, the user's track, a reference film's soundtrack (a voice in it comes back as "vocals").
- Speed: the models run on this machine's GPU. On an M2 Pro with 16 GB, planning and hearing take about 20 seconds per take; rendering about 3 minutes to load, then 2–3 minutes per 64-second take, slower while renders or a voice run beside it. On a machine with an NVIDIA card (12 GB or more) a take takes seconds: start ACE-Step's API server there (`start_api_server.bat` on Windows, `start_api_server.sh` on Linux, with `HOST=0.0.0.0`, `API_KEY=--api-key <key>` and `LM_MODEL_PATH=--lm-model-path acestep-5Hz-lm-1.7B` set at its top, port 8001 open to the local network only), then here `MOTION_DESIGNER_ACESTEP_URL=http://<its address>:8001 MOTION_DESIGNER_ACESTEP_KEY=<key> python3 $SKILL_DIR/scripts/music_gen.py music.json`. The server plans and renders in one go; hear its takes here with `--hear`.
- Plans and takes already made are kept; delete one to make it again (a changed caption or seed plans again).
- `audio/SOURCE.md` records "original, made with ACE-Step 1.5 (acestep-v15-turbo, acestep-5Hz-lm-1.7B)", every take with its caption, its seed and what ACE-Step heard in it, which one was used, the date and the bars used.

## 2. Listen

```bash
python3 $SKILL_DIR/scripts/beats.py audio/source/track.mp3 --json audio/grid.json
```

```
104.997 BPM, beat 0.5714 s, bar 2.2858 s, bar 1 starts at 2.285 s
downbeat clear (bars from this beat change +16% more sharply than from any other)
                   loudness                                            hits  bright  fill  crest
bar   6    13.71s  ###########################                         3.25    1.9k   30%   14 dB
bar   7    16.00s  ###################                      breakdown  1.00    1.2k    9%   17 dB
...
sound: 5.2 attacks a second, 1.7 kHz, fill 26%, crest 13 dB; busy, warm, open, even: a bed that leaves room for words and sounds
```

It prints the tempo, where bar 1 starts, and a row per bar: its loudness with the bars where the energy jumps (`drop`) or falls (`breakdown`), then how the bar sounds: `hits`, strong attacks per beat (how busy); `bright`, the spectral centroid; `fill`, how much of the spectrum is taken (a few clear notes near 5%, a wall of sound over 30%); `crest`, peak over average (room for hits). The last line sums the track up and says whether it can be a bed. `--sheet sheet.png` draws its spectrogram (low to high from the bottom, 40 Hz to 16 kHz) with a line on every bar, a brighter one every four, and a mark over each drop (green) and breakdown (red): look at it like a contact sheet. Vertical strokes are hits, horizontal ones held notes, wavy stacks in the middle a voice, a dark band a bar where the drums drop out.

Against the sound brief: a bed has fill at or under 30%, crest of 12 dB or more, and is not busy over the text; a lead can fill the frame. A take that fails is dropped, not rescued by mixing it lower. Then play the take the numbers chose to the user with the stills: their ear decides. The tempo and bar 1 come from a straight line through the attack of every beat, to a fraction of a millisecond; "one" is the beat from which bar-to-bar loudness changes are sharpest, since sections start on downbeats. `--beats-per-bar 3` for music in three.

Sanity-check before using the grid:
- The tempo is what you would tap along to (if it is double or half, the track is unusual; say so and use the bar table to confirm).
- Drops and breakdowns fall 4, 8 or 16 bars apart. If the downbeat is reported `uncertain`, or a section visibly starts a beat before or after a bar line in the table, shift `bar1` in the JSON by one beat (±`60 / bpm`) and cut from the corrected grid.
- The section you will use has a steady tempo (no ritardando, no tempo change).

## 3. Choose the bars

The film is `BEATS` long; `BEATS = bars × beats_per_bar`.
- Decide which film beat must hit the drop (the reveal). It is always a downbeat: 1, 5, 9, … (`1 + 4k` in 4/4).
- Start bar `A = drop_bar − (reveal_beat − 1) / 4`.
- Start on a phrase start (a bar where a section begins) and make `A + bars` a phrase boundary too, so the loop joins two phrase edges.
- If the story needs more or less time, change the story's holds, never the music's speed.
- Line the take's shape up with the energy map: a break (drums out, a low `fill`) under the hook's last line, the groove back on the reveal, a quiet bar under the end card, a fill under the call to action.

## 4. Cut

```bash
python3 $SKILL_DIR/scripts/music_edit.py audio/source/track.mp3 audio/grid.json --from-bar 4 --bars 25 --out audio/edit
```

```
bars 4–28: 5.7404s → 52.2571s, 100 beats at 128.998 BPM = 2791 frames (46.5167s at 60 fps)
film: BEATS 100, DURATION 2791 / 60, beat n at (n - 1) * 0.465125s
  track bar 17 (drop) → film beat 53 at 24.187s
```

It writes `audio/edit.wav` and `audio/edit.m4a`, exactly a whole number of frames long, with 6 ms / 12 ms edge fades so neither end clicks. Then set the film's clock to it, on the first line of `scenes.js`:

```js
film({ BPM: 128.998, BEATS: 100, holds: [...] });  // the printed BPM, unrounded
```

## 5. Sounds for the actions

In a story, feature cards or a type-led film, what moves on screen makes a small sound. The film says where they go: `cues()` in `scenes.js` returns `[sound, time, {note, gain, pan}]` with the same times `apply()` uses (the story template's is a working example; `headlineCues(key, t0)` gives a tick for every typed letter and a swish when the accent's stroke draws).

| Sound | For |
|---|---|
| `tick` | a typed letter, a counter's step |
| `click` | a toggle, a tap |
| `pop` | a check, a button, an icon appearing (`note` picks its pitch) |
| `thud` | a card or panel landing |
| `whoosh` | a scene wiping in (`pan` toward the side it comes from) |
| `swish` | a stroke drawing |
| `blip` | a bar growing, an item added (`note` climbs the scale) |
| `chime` | the logo, the end |
| `hop` | the character jumping |

```bash
node $SKILL_DIR/scripts/render.mjs cues src/index.html audio/cues.json
python3 $SKILL_DIR/scripts/sfx.py audio/cues.json --key "G major" --music audio/edit.wav --out audio/mix
```

`sfx.py` synthesizes every sound here (original, nothing downloaded), tunes the pitched ones to the music's key (the key `--hear` gives, or the take's), writes `audio/mix-sfx.wav` and mixes it over the music: the bed at `--music-gain` (0.32) with a dip at 3.5 kHz to make room, the whole at −16 LUFS, `audio/mix.wav` and `.m4a`, exactly the film's length. Render with `--audio audio/mix.m4a`; a voiceover goes on top with `"music": "audio/mix.wav"`. A sound that runs past the end continues at the start, as the film loops.

Keep them few and small: one sound per action that matters, starting on the frame the thing moves. A sound for everything is noise.

## 6. Verify

- `python3 $SKILL_DIR/scripts/beats.py audio/edit.wav` reports the same tempo and bar 1 at ≈ 0.00 s (or one bar length, the same point).
- `FILM_INFO.frames` in the film (open it with `?render` and read `window.FILM_INFO`, or `check.mjs`) equals the printed frame count.
- The beat map in the README lists the drop at the printed film beat and time.

## Rules

- Cut only on bar lines; never time-stretch, re-pitch, loop sections or splice mid-bar.
- Sounds for the actions follow the sound brief: on for story, feature cards and type-led films, off in a product film unless the user asks.
- Don't call a track free for commercial use unless its licence says so in words that cover this use.
