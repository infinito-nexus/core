---
name: motion-designer
description: "Make short videos from code: launch films of apps (the real UI in an iPhone or a laptop window, or a story in panels), and any other short video: titles and stings, kinetic type, explainers, data videos, music videos, photo montages, and lower thirds or captions over footage, with a library of effects and transitions. Cut on the beat to an original track made for it or the user's, with an optional local voiceover (Chatterbox or Kokoro), checked frame by frame and rendered to MP4, a muted loop, a poster and one self-contained HTML. Also makes or cuts a track to the bar, writes and mixes a voiceover, and installs the tools it needs after asking. Use when the user wants a launch video, promo, teaser or product film of an app, or any short motion video, title, explainer, animated chart or captioned clip, wants to change such a video's story, style, pacing, music or voiceover, wants a track made or cut to a video, or asks what the tool needs to run."
argument-hint: "[app project dir] [mobile | desktop] [square | vertical | landscape] [length, e.g. 45s]"
---

# motion-designer: films from code

You direct and build short videos: most often a film of an app in use, and any other short motion video on the same engine ([types](reference/types.md#beyond-app-films)). The app's own interface, rebuilt from its code and screenshots or captured from its web frontend, lives inside a device that one camera films, and every move lands on the music's beat. The film is a page whose every frame is a pure function of time, `seek(t)`, so it renders frame-exactly, loops without a seam, and can be checked frame by frame.

- **Blank**: full-frame shots on a canvas of any size, for titles, kinetic type, explainers, data, music videos and montages (`templates/blank`). **Overlay**: a clear background drawn over the user's footage, for lower thirds, captions and callouts (`templates/overlay`). Both lean on [effects](reference/effects.md).
- **Mobile**: an iPhone (`templates/mobile`). **Desktop**: the app's window on a laptop display with menu bar, dock, pointer and a lid that closes (`templates/desktop`); web apps in the same window with `browserBar(url)`. **Story**: a hook, the product's arrival, features as panels, the brand's character, and an end card (`templates/story`, [types](reference/types.md)).
- `SKILL_DIR` in every command is `${CLAUDE_SKILL_DIR}`, the folder holding this file, with `scripts/`, `templates/` and `reference/`. Write it out as that absolute path in each command.
- Any agent can run this skill. Where a step says **Plan**, **Ask**, **Look**, **Delegate**, **Background** or **Send**, [harness](reference/harness.md) maps it to your tools (Claude Code, Codex, others).

## 1. Start from the project's state

Take the first row that matches and do only what it says; the rows below it do not apply.

| State | Do |
|---|---|
| A question about the skill, or what it needs to run | Answer it. For setup, run `bash SKILL_DIR/scripts/doctor.sh` and follow [setup](reference/setup.md). |
| Music only: make a track, or cut one to a film | [music](reference/music.md), nothing else. |
| Voiceover only, over a film that exists | [voiceover](reference/voiceover.md), nothing else. |
| A film folder exists and the user names a change | Make that change. Read only the reference for it (§ 5), find the code with `grep -n`, then run the checks and review only the changed stretch. No new brief. |
| A film folder exists and the user says go on | Read `brief.md` (its `## Status` says where it stopped) and the beat map in `README.md`, then continue from that step. |
| A new video that is not about an app | As a new film, with the brief built around what the video says, `blank` or `overlay` as the template, and [effects](reference/effects.md) read at step 3. |
| A new film | `bash SKILL_DIR/scripts/doctor.sh`; if something is missing, follow [setup](reference/setup.md) (say what and why, install only after a yes). Then § 2 from step 0. |

## 2. Workflow

Stop for the user's go-ahead after step 0 and again after step 2 unless they asked you to go straight through; after that, work without asking except where [rights](reference/rights.md) says to. At the end of every step, rewrite the `## Status` section at the bottom of `brief.md`: the step reached, what is done, what is next, what is open. With it and the files on disk, a fresh session continues where this one stopped.

0. **Brief, as a plan** (**Plan**: in Claude Code `EnterPlanMode`, then `ExitPlanMode` with the brief; unless the user asked to go straight to building or gave you a complete brief). Find the product's name, read what it does and which flows are worth filming, write a brief for this product alone ([brief](reference/brief.md)), with the film's type ([types](reference/types.md)).
1. **Materials.** Find what you can: the app's code (screens, tokens, fonts, icons, copy), a Simulator or desktop build, brand assets, screenshots or recordings. Ask only for what you can't find: the music (the user's track; without one, make an original with [music](reference/music.md#make-one) or, with their go-ahead, search [music sources](reference/music-sources.md)), format and length, features that must appear, claims to avoid. Confirm every feature you plan to show exists and works that way: read its code and try it.
2. **Concept.** Offer two or three [styles](reference/styles.md) that suit the app. Write the story in beats (one visual change per beat, a hold after each result, the biggest reveal on the drop), a beat-map table (beat, time, what happens), the screens and assets needed, and four stills from the template in the chosen style: the opening, the key product moment, the drop, the final frame. List your assumptions. A social cut (15 to 25 s) shows the app's strongest action in the first two seconds. For an App Store app preview, explain guideline 2.3.4 first ([rights](reference/rights.md)).
3. **Build.**
   - `bash SKILL_DIR/scripts/new_film.sh <film-dir> mobile|desktop|story|blank|overlay`; open `src/index.html` in Chrome to preview and scrub.
   - Set the clock on the first line of `scenes.js`: `film({ BPM, BEATS, holds })`.
   - Pack the app's look: `swift SKILL_DIR/scripts/symbols.swift <film-dir>/assets/sym plus@semibold …` for SF Symbols, then `python3 SKILL_DIR/scripts/assets.py <film-dir>/src/assets.js --font "Family=font.ttf" --img icon=AppIcon.png --sym <film-dir>/assets/sym`. The app's family goes first in `film.css`, the style's tokens in its `:root`.
   - Rebuild each screen in `scenes.js` from the real app, in app or window points; write every time as a story beat `B(n)`. For web-tech desktop apps, capture the real UI instead ([capture](reference/capture.md)). Read [motion](reference/motion.md) and [phone](reference/phone.md) or [desktop](reference/desktop.md) first.
4. **Sound** ([music](reference/music.md)): follow the sound brief. Make the track if there is none, listen with `beats.py`, pick bars so its lifts and breaks land on the film's, cut it to `<film-dir>/audio/edit.m4a`, put its `BPM` and `BEATS` in `film({...})`. In a story, feature cards or type-led film, give the actions their sounds (`cues()`, `sfx.py`).
5. **QA loop** ([qa](reference/qa.md)):
   - `node SKILL_DIR/scripts/check.mjs <film-dir>/src/index.html`: no clocks, timers, randomness or CSS animation, no page errors, the loop closes, frames identical in any seek order.
   - **Delegate** the looking to [reviewers](reference/reviewer.md), one per stretch of about 12 s and per kind (overview, transitions, text), plus one at phone size for the whole film, all at once. Each scores its stretch from 1 to 10. Fix what they report, then send them back to what changed. Repeat until every report reads `clean` with every score at 8 or more.
6. **Render** (**Background**, about 0.4 s a frame): `node SKILL_DIR/scripts/render.mjs video <page> <film-dir>/out/<name>.mp4 --audio <film-dir>/audio/edit.m4a --scale 2` (add `--blur 8` for motion blur when the film has fast moves; it renders 8 times slower), then the loop, poster and any smaller copy ([qa](reference/qa.md#deliverables-to-render)). `node SKILL_DIR/scripts/render.mjs verify <page> <film-dir>/out/<name>.mp4` checks frames, size, duration and a frame against a still.
7. **Voiceover**, if asked ([voiceover](reference/voiceover.md)): let the user pick the voice engine, then mux the mix over the rendered picture.
8. **Single file.** `python3 SKILL_DIR/scripts/build_single.py <film-dir>/src/index.html <film-dir>/dist/<name>.html`, then `check.mjs <page> --dist <film-dir>/dist/<name>.html` proves it shows the same pixels.
9. **Report** in the user's language: the film beat by beat, what you checked and how, the files and the post text, and what is still open (music licence, logos, voices, unverified claims). **Send** the video.

## 3. Deliverables

In a film folder in the project (default `docs/launch-film/`, or `tmp/launch-film/` when it must stay out of git):

| Path | What |
|---|---|
| `brief.md` | the approved brief, with `## Status` at the bottom |
| `src/` | the film: `index.html`, `film.css`, `core.js`, `device.js`, `scenes.js`, `main.js`, `assets.js` |
| `out/<name>.mp4` | the render with music (`out/` stays out of git) |
| `out/<name>-loop.mp4`, `out/<name>-poster.png` | a muted loop for autoplay, and the hero frame |
| `out/<name>-voiceover.mp4` | if asked: the same picture with the voiceover mix, plus `.srt` captions |
| `dist/<name>.html` | one self-contained file (fonts, images, music inlined) |
| `out/<name>-post.txt` | two or three sentences to post with the film: what the app does and for whom, in its own words, with the link |
| `README.md` | the beat map with times, the style, how to preview, check, render and rebuild, sources and rights |

## 4. Keep the context small

A session pays for everything in its context again on every turn, so what stays in it matters more than what is read once.

- **Pictures go to reviewers.** Look at images yourself only for the four concept stills, frame 0 and the poster.
- **Read code by place.** `grep -n` for the scene or function, then read that range. Read a file whole once at most; don't read back a file you just wrote, the templates (the copy in `src/` is the same) or the scripts (run one without arguments for its usage).
- **Read a reference when its step starts**, once, and only the ones the step names.
- **Keep output short.** The scripts print summaries; give any `ffmpeg` you run `-v error` and `ffprobe` `-v error`; send long logs to a file and read its tail.
- **Fewer turns.** Make independent calls together. Run renders in the **Background** and check the file once, instead of polling.
- **Restart at the seams.** After the brief is approved and after the film passes QA, everything needed is on disk. If the session is long by then, tell the user they can start a fresh one there with "continue the launch film".

## 5. Hard rules

Every video:

- **Deterministic.** Every property is computed from `t` with easings, closed-form springs and `track()`. No CSS transitions or animations, timers, `Math.random`, `Date`, or state carried between frames. Spinners, waveforms, carets and typing are functions of `t`.
- **Readable on a phone.** Each result holds 1 to 2 s before the next action. Text that matters is at least about 20 px on the stage: move the camera in rather than shrinking the film. No truncated labels, text cut by a mask or the frame edge, text crossed by motion, one-frame flashes, or layers popping.
- **Local only.** No external libraries, fonts, images or CDNs in the film unless the user agrees; everything is packed into `assets.js` and inlined in the single file.
- **Never overwrite the user's source assets, footage or app code**; derived files go in the film folder.

An app film also:

- **The device is always there.** Mobile: once the screen opens, the app lives inside the iPhone; close-ups crop top and bottom but keep its sides, island or status bar. Desktop: the app is in its window, with the traffic lights or caption buttons in frame, first on the canvas, then on the desktop, then on the laptop. Never app UI full-bleed.
- **Real features, fictional data.** Only what the app does, the way it does it; opt-in features shown being used, not as defaults; nothing implied about on-device processing that isn't true. Every name, amount, file and person is invented.
- **Motion from the app itself.** Transitions come from shapes and actions: a row opens into the window, a button grows into a sheet, a card lifts into a preview, the palette closes into what it opened. No crossfades between scenes, blur-ins, brightness reveals, glass or glow, 3D flips, particles, random pointer paths, stock imagery.
What viewers asked for: to see it is a phone or a desktop app at every moment; slow enough to follow, one action per beat with a hold after each result; nothing that looks broken ("Savi" or "Uncategori…" gets reframed until it fits, badges sized from DOM-measured text); a voice clearly on top of the music, with the music still present between lines.

## 6. References: read when

| Read | When |
|---|---|
| [brief](reference/brief.md) ([example](reference/brief-example.md)) | step 0 |
| [types](reference/types.md) | step 0, choosing the film's shape |
| [styles](reference/styles.md) | step 2, or a change of look |
| [motion](reference/motion.md) | step 3, or a change to timing, transitions or the camera |
| [effects](reference/effects.md) | step 3 of any video that is not an app film, or when a look or a transition is asked for by name |
| [phone](reference/phone.md) / [desktop](reference/desktop.md) | step 3 for that device, or a change to it |
| [capture](reference/capture.md) | a Tauri, Electron or web app whose real UI can be filmed |
| [music](reference/music.md), [music sources](reference/music-sources.md) | step 4, or any music request |
| [qa](reference/qa.md), [reviewer](reference/reviewer.md) | step 5 and after every fix |
| [voiceover](reference/voiceover.md) | step 7, or any voice request |
| [rights](reference/rights.md) | claims, data, music, brands, voices, App Store previews |
| [setup](reference/setup.md) | something is missing, or the user asks what it needs |
| [harness](reference/harness.md) | the first time a step names an action you don't know how to take |
