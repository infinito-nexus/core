---
name: presentaitor
description: Make narrated presentation films and multi-chapter demo series of any product, project or release, in the user's own brand or a ready preset, from code, existing screen recordings, or both, with a narrator voice and a music track. Use when the user wants a demo video, a feature walkthrough series, a release presentation, or a video that presents work in their place, or wants to change the text, voice, music, look or scenes of such a film.
author: Alejandro Roman
---

# presentaitor

Films that present the work so nobody has to stand in front of a camera: one narrator, one look, one track, chapter after chapter. The film engine is `engine/` (motion-designer by kaventro, MIT, see `engine/LICENSE`); this skill adds the setup interview, presets, a scene library and the workflow for a series.

`SKILL_DIR` for every engine command is `<this folder>/engine`. Read `engine/ENGINE.md` once at the start and follow it; where this file and ENGINE.md differ, this file wins.

A change to a film that already exists (text, voice, music, look): read `reference/changes.md` and take the cheapest path there; skip the interview.

## 1. Setup interview

Every new film or series starts by asking the user, one round of questions at a time, and offering the default for each. Record every answer in `SERIES.md` in the work folder; every chapter, and every agent building one, reads it first.

| Topic | Ask | Default |
|---|---|---|
| Brand | preset or custom? Custom: canvas, accent and text colours (hex), logo file, two fonts (display + mono), dark or light | preset `infinito` (below) |
| Voice | the default narrator, or the user's own 10-20 s sample? A real person's voice needs that person's consent for this use; a voice generated on a third-party service needs terms that allow cloning it | Bella |
| Music | the default track, the user's track, or search free sources (`engine/reference/music-sources.md`, user approves the download)? | pulse (original, ACE-Step 1.5) |
| Series | chapters (one idea each), length per chapter, intro and end card, language | intro + chapters of 60-90 s + end card with the music credit |
| Output | split chapter videos, one long video with chapter markers, or both? Write it as `Output: split`, `Output: long` or `Output: both` in `SERIES.md`; re-renders read it and never ask again | both |
| Captions | kinetic captions on or off (one toggle, `"captions"` in `voiceover.json`) | on for a series with a long video and for phone films, off elsewhere |
| People and data | the names on screen, invented data, what must never show (credentials, real customer data) | invented names, passwords only as dots |
| Story rules | continuity rule for logins, honesty notes (what the footage does not prove), names in narration or neutral | the continuity rule below |
| Scenes | per chapter, propose 3-5 scenes from `reference/scenes.md` and let the user swap them | the agent's proposal |

### Presets

| | `infinito` |
|---|---|
| Look | dark techy canvas `#0A0D1A`, accent `#142CAD`, bright accent `#4F6BFF`, text `#EFEFEF`; Inter 500/800 + JetBrains Mono 600; mono uppercase kickers; `scanLayer(0.06)`, `grainLayer(0.08)`, vignette 0.5 on motion and 0.2 over light footage |
| Files | `defaults/brand/film.css` (copy over the film's `src/film.css`), `defaults/brand/logo.png`, `defaults/brand/example-intro-scenes.js` |

A custom brand starts from `defaults/brand/film.css`: replace the `:root` tokens with the user's colours and fonts, keep the class names. Pack fonts and logo into each film with the engine's `assets.py --font "<Family>:<weight>=<file>" --img logo=<file>`.

### Defaults

| | Default | Where |
|---|---|---|
| Narrator | Bella (synthetic, friendly female tech voice, made locally with Kokoro, royalty-free), Chatterbox: `exaggeration 0.52`, `cfg_weight 0.5`, `temperature 0.75` | `defaults/voice/narrator.wav`, rules in `defaults/voice/CONSENT.md` |
| Music | "pulse", original, made with ACE-Step 1.5 (no attribution required), 104.9 BPM, 96 s; alternative "Industrial Cinematic" (Kevin MacLeod, CC BY 4.0, 110 BPM) | `defaults/music/` (`pulse.mp3` + `grid-pulse.json`, `industrial-cinematic.mp3` + `grid.json`, `SOURCE.md` with tempo notes and credit lines) |
| Mix | `music_gain 0.75`, `duck_ratio 2.8`, `-16 LUFS`; voice 16-22 dB over the music while speaking | `voiceover.json` |

## 2. A series

1. **Footage.** Prefer the user's existing recordings over running the app again. A recording too fast to read (a scrolling terminal) gets rebuilt in HTML from its real data instead. Stretch footage with freeze frames where the voice needs time; cut what breaks continuity or shows what must not show.
2. **Continuity rule** (default, the user may change it). The series reads as one session: a login screen appears only when the user on screen changes (the first sign-in, and each switch to another person). Every other login is cut. Sample frames into contact sheets to find them.
3. **Concept per chapter.** Scenes from `reference/scenes.md`, narration lines, a beat map; show it to the user before building.
4. **Voice first.** The narration times the picture; there is no flag for it. Write `voiceover.json` with `"bpm"`, `"scenes"` (each a list of line ids) and lines without start times, then build the page against `line(id)` and `scene(id)` instead of fixed seconds. Read `reference/voice.md` first. One folder per chapter, named `NN-<slug>`, next to `SERIES.md`.
5. **Iterate with previews.** `python3 <SKILL>/tools/film.py preview <film>` speaks the changed lines, lays out `timing.json`, cuts the footage, renders at 30 fps and half scale and writes `out/<name>-sheet.html`: one card per line (thumbnail, text, times, silence warnings); clicking a card plays the preview from there. Fix the page, the lines or the scenes and preview again; unchanged scenes are reused.
6. **Render.** `film.py render <film>` is a full-size draft, `--final` the hand-over quality. In a series, `film.py render <series> --chapter NN [--final]` rebuilds one chapter (only changed takes, only scenes whose timing, footage or code changed) and, when `SERIES.md` asks for a long video, joins the series again. Every render runs the silence check: more than 1.2 s without speech warns, more than 2.5 s fails the render (music-only intro and outro excepted). `film.py join <series>` joins without rendering.
7. **Build in parallel.** One agent per chapter is fine for building and rendering (12 cores render about 7 chapters at once, about 1 s per frame each).
8. **Hand over.** Split chapters: compress each final (`-crf 26 -r 30`), name files `<project>-NN-<chapter>.mp4`. Long video: `out/<series>-long.mp4` (MP4 chapter markers), `out/chapters.txt` (paste into the YouTube description) and `out/<series>-long.html` (player with a chapter menu). Report each chapter with its cuts, claims not shown on screen and open points, and give the copy command. Keep the previous finals as a backup until the user approves.

## 3. Motion presets

Scenes animate with the presets in `engine/templates/shared/presets.js`; every one is a pure function of t (never a CSS transition). Pass an object to override any default, or `tune(name, {...})` once to change it for the whole film. Defaults live in `preset-defaults.js`.

| Preset | Call | What it does |
|---|---|---|
| reveal | `reveal(split(el, "word", true), t, line("n01").start)` | rise per word through the mask |
| focus | `applyFocus($.cam, focus(t, [{ line: "n03", rect, zoom: "punch" }]))` | camera glides to each line's focus rect; `zoom`: `subtle`, `normal`, `punch` or a number; `tune("focus", { intensity: 0.6 })` scales every zoom. Over footage: `window.FOOTAGE_CAMERA = (t) => focus(t, shots)` and the render zooms the footage |
| cursor | `cursorLayer()` in the markup, `cursor(t, [{ t, x, y, click: true }, ...])` | bezier cursor with overshoot, click dip and ripple |
| captions | `captionLayer()`, `captions(t, lineWords(["n01", "n02"]))` | bounce-in captions from the takes' word timings; shown only when captions are on |
| spotlight | `spotlightLayer()`, `spotlight(t, [{ t, rect }], [on, off])` | dims the frame, the cut-out glides between targets |
| emphasize | `emphasizeLayer()`, `emphasize(t, "n05", rect, "Label")` | callout label tied to a line |
| morph | `morph(t, el, fromRect, toRect, open, close, { source, content })` | FLIP morph, content fades in, source hidden |
| transition | `transition("whip")` as a `sequence()` join, `beatCuts(keys)` | whip push on the beat grid, a cut every 2 beats |
| parallax | `parallax([back, mid, front], t, t0, t1)` | side pan over depth layers |
| tilt | `tilt(t, t0, { wrap, screen, gloss, shadow })` | hero tilt-in of a device |
| chart | `chart(svg, t, t0, data, { labels })` | bars with count-up labels |
| aurora | `auroraLayer()`, `aurora(t)` | gradient background, no CSS blur |
| motionBlur | `motionBlur(host, t, (el, u) => place(el, u))` | sub-frame copies of a moving element; off in previews |
| rackFocus | `rackFocus([back, mid, front], t, t0, 2, 0)` | blur per depth layer, focus shifts |

`python3 <SKILL>/tools/film.py playground` builds one test page per preset (scrubber, play, sliders, state, "Export defaults"); `--check` loads them all headless. A new technique enters the library only after its playground page has been tuned and approved: add its function to `presets.js`, its defaults to `preset-defaults.js` and its page to `engine/playground/demos.js`; `film.py playground --apply <name>-defaults.json` writes exported slider values back.

## Rules

- Real features, invented data. Narration claims only what the footage or the repo shows; anything else is listed for the user.
- Passwords stay dots on screen; never open env or spec files holding credentials.
- The music credit and the engine's MIT notice stay in place.
