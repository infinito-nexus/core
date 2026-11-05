# Motion

The engine is `core.js` in the film. Every function takes the time `t` and returns a value; `apply(t)` in `scenes.js` sets every property of every layer from `t` alone.

## The grid

```js
film({ BPM: 128.998, BEATS: 100, holds: [[7.9, 3], [14.5, 2]] });   // first line of scenes.js
const B = (b) => (b + HOLDS.reduce((s, [at, len]) => s + (b >= at ? len : 0), 0) - 1) * FILM.P;  // core.js
```

- **Story beats.** Write every time as `B(n)`: story beat `n` is the n-th visual change. `B(6) + 0.12` means 0.12 s after beat 6.
- **Holds.** `[at, len]` adds `len` whole beats before every story beat `≥ at`. Put a hold after each result the viewer must read (a saved row, a filled form, a chart). Two beats at 120–130 BPM is about a second. Holds are whole beats, so later actions stay on the beat. Set `at` just after the last action of the result (7.9 holds after beat 7 finishes).
- **Length.** `BEATS` is story beats plus all holds; the music cut must have exactly that many beats (`music_edit.py` prints them, see [music](music.md)), and a whole number of bars. `FILM.frames` rounds to whole frames.
- **No track yet?** Time the film at the tempo you expect (120–128 BPM) and cut the music to it later; only `BPM` changes.
- **Formats.** 1440 × 1440 square (posts; export 1080 from it if a platform needs it), 1080 × 1920 vertical (Reels, Shorts, TikTok), 1920 × 1080 landscape (site hero, YouTube): `film({ W, H, ... })`. Recompose the cameras and caption positions for the new frame.

## Primitives

| Call | Use it for |
|---|---|
| `prog(t, t0, dur, E.x)` | 0 → 1 over `dur` with an easing: moves, fades of chrome, clip reveals |
| `spring(t, t0, response, damping)` | things that land: sheets (0.5, 0.9), a button popping in (0.42, 0.62), text rising (0.5, 0.88). Can overshoot above 1; `clamp` it when overshoot would uncover something |
| `track(t, base, keys)` | a value that moves several times (a scroll offset, a camera zoom): `keys = [{ t, d, to, e }]` or `{ t, to, spring: [r, d] }`; each move starts from the previous target |
| `press(t, t0, depth)` | a tap on a control: dips to `depth`, springs back |
| `pulse(t, t0, dur)` | 0 → 1 → 0 accent (a dot that beats once) |
| `rise(el, p)` / `sink(el, p)` | text inside a `.mask` slot coming up into view / leaving upward |
| `roller(host, css)` + `roll(r, t, steps)` | a number that changes: the old value slides out as the new one rises |
| `mixRect(a, b, p)` + `rectCss(el, r)` | a shape morphing between two rects with radius (dot → screen, row → card, screen → icon) |
| `measure(text, size, weight, css)` | real laid-out text width, for badges, underlines, centring. Never canvas `measureText` |
| `show(el, on)` | visibility; a hidden parent hides its children |
| `sym(key, size, color)` | an SF Symbol packed into `assets.js` |

Easings: `E.out` for arrivals, `E.in` for exits, `E.smooth` for camera moves, `E.inOut` for shape morphs, `E.snappy` for UI state changes (a card resizing, a list shifting).

## Vocabulary

Name moves by feel and keep one set per film:

| Feel | How |
|---|---|
| **arrive** | `E.out` or a spring with a touch of overshoot; things come from below or from the element that caused them |
| **settle** | a spring with damping ≥ 0.86; for panels, cards, sheets, selections |
| **depart** | `E.in`, faster than the arrival; last in, first out |
| **snap** | `E.snappy`; UI state changes: a list shifting, a card resizing |
| **glide** | `E.smooth` over 0.8–1.2 s; camera moves |
| **drift** | 2–3 % over a hold; the camera never fully stops |

- **One relay object.** A small brand element (a dot, a row, a line) travels through the whole film (it becomes the device, marks what changed, returns to the logo) so the first and last frames rhyme.
- **An accent with one meaning.** The accent marks *now* or *just changed*; new values arrive in it and cool to the neutral ink. Don't spend it on decoration.
- **Something moves on every beat, scenes change on bar lines.**

## Timing that reads

- One visual change per beat. An action takes 0.3–0.5 s; its result then holds for 1–2 s (a hold) before the next action.
- Text comes in with `rise` in 0.35–0.45 s, staggered 0.06–0.1 s per line; it leaves faster (0.25–0.3 s, `E.in`), last line first.
- A tap is a beat on its own: the finger marker appears 0.08 s before the beat, the control presses on the beat, the next screen starts 0.1–0.15 s after it. Never tap something in the same beat it appears.
- Camera moves take 0.8–1.2 s (`E.smooth`) and happen between actions, never during one. During a hold the camera keeps easing in (`drifted`, 0.8 % a second) so a still screen is not a frozen frame.
- The biggest reveal lands on the music's drop. Put the drop in the beat map first and plan backwards from it.
- End where you started: the frame after the last equals the first, so the film loops. Ambient motion (breathing, a camera sway, a float) uses `loop(t, cycles)`, which completes whole cycles over the film.

## Transitions that worked

Use the app's own shapes and actions to get from one scene to the next.

- **Dot → phone.** A brand dot (from the wordmark) flies to the stage centre and shrinks as the screen opens out from under it (`mixRect(dot, FULL)`), then the frame and bezel grow (`edge` 0 → 1) and the side buttons appear.
- **Tap → sheet.** Finger marker, `press()` on the button, the sheet springs up from the bottom (response 0.5, damping 0.9), its content rises in after it.
- **Save → result.** The sheet drops away (`E.in`), the new row slides into the list and pushes the others down (`E.snappy`), the balance rolls to the new value. Hold.
- **Voice input.** Mic button → a listening card springs up; the waveform animates as a function of `t` (a highlight band sweeping `(t - t0) / 0.9 % 1`); the spoken phrase appears beside the phone, line by line, as said; stop → the card shrinks to a working state with a spinner (rotation from `t`) → the form fills field by field, and underlines in the phrase connect words to the fields they filled.
- **Receipt scan.** The camera sheet slides up over a photographed receipt (drawn in HTML: paper with a zigzag edge, points ordered right to left); a detection quad locks onto the paper (spring from 1.22× to 1×); shutter press; the page straightens and flies into a thumbnail; a reading state with a spinner; the review card springs in with the recognised fields rising one by one.
- **App ↔ Home Screen.** The app screen shrinks into its icon on a Home Screen grid (rect morph to the icon's rect), the status bar turns white over the wallpaper, widgets show the numbers the film just produced.
- **Close onto the icon.** At the end the screen morphs into the app icon while the camera scales so the icon lands at stage centre at its final size; the icon opens as a circle clip; the icon becomes the brand dot and flies home to the wordmark.
- **Caption beside the phone.** The camera moves the phone to one side; the caption rises in masks line by line on the free side, never over the phone, and sinks out before the phone moves back.

## Traps

- Text that comes to rest at a fractional pixel position: Chrome may draw it half a pixel apart depending on what was drawn before, which `check.mjs` reports as frames that differ by seek order. Round resting positions of type (`Math.round`), keep fractions for motion only.
- Content appearing while the screen is still opening: start content after the rect morph ends.
- A layer shown with `show()` one frame before its transform starts: it flashes in its end position. Show it at the same `t` the motion starts from its start position.
- `spring()` overshoot pushing a sliding sheet past its rest and uncovering the screen behind it: `clamp(spring(...), 0, 1)`.
- Two moves on the same property from different scenes: give each layer one owner in `apply`, or combine with `track()`.
- Caches keyed by anything other than the value they mirror (a text node cache is fine; a "last beat" counter is not).
