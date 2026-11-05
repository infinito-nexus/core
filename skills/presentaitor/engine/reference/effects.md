# Effects

`templates/shared/fx.js` is in every film. Each effect is a function of `t`, so it seeks, loops and renders like the
rest of the film; randomness comes from `hash(i, seed)`, never `Math.random`. Read this list, not the file. Call the
effects from `apply(t)`; the ones marked *build* set something up once and are safe to call every frame.

## Timing and randomness

| Call | Gives |
|---|---|
| `hash(i, seed)` | a fixed pseudo-random number in [0, 1) for an integer |
| `noise(x, seed)` | smooth noise in [-1, 1]; feed it `t * rate` for drift |
| `stepOf(t, rate)` | the step number at `rate` per second, for effects that change in steps (flicker, scramble) |
| `stagger(t, t0, i, gap, dur, ease)` | progress 0..1 of item `i` in a staggered group; keep `n × gap` under about 0.5 s |
| `sequence(t, shots)` | runs a cut list: `[{ k: "s1", t0: 0 }, { k: "s2", t0: B(5), join: ["push", 0.6, { dir: "left" }] }]`. Each `k` is a full-frame layer (`class="shot"`); it shows each one in its time and plays the join between them |

Joins for `sequence`: `cut`, `dissolve`, `push` (`dir` left, right, up, down), `cover` (the new shot slides over), `zoom`
(through the old shot into the new), `whip` (fast push with motion blur), `wipe` (`from` a side), `iris` (a circle at
`x`, `y`). Put the shot's own motion on elements inside the layer, never on the layer, since the join owns its
transform, opacity, filter and clip.

## Text

| Call | Effect |
|---|---|
| `split(el, "char" \| "word", masked)` *build* | wraps each letter or word in a span and returns them; `masked` puts each in its own mask for rises |
| `rise(el, p)` / `sink(el, p)` | in from below its mask / out above it |
| `typewriter(text, t, t0, cps)` | the text typed so far; pair with `caret(t)` for a blinking caret |
| `scramble(text, t, t0, dur, seed)` | letters resolve left to right out of flickering glyphs |
| `countUp(t, t0, dur, from, to, fmt)` | a number counting to its value; use `font-variant-numeric: tabular-nums` |
| `sweep(el, p, color, width)` | a shine through the letters (also over split words) |
| `roll(roller(host, css), t, steps)` | a value that rolls to the next one (in `core.js`) |

## Shapes and reveals

| Call | Effect |
|---|---|
| `drawPath(path, p)` | an SVG stroke drawn along its length: lines of charts, underlines, signatures, maps |
| `wipe(el, p, from)` | reveal from a side |
| `iris(el, p, x, y)` | reveal in a growing circle |
| `confetti(layer, t, t0, { n, x, y, colors, seed })` | a burst of pieces that fly, spin, fall and fade, all in closed form |

## Camera

| Call | Effect |
|---|---|
| `moveCamera(el, { x, y, s, r })` | moves a world layer |
| `kenBurns(el, t, t0, t1, from, to)` | slow push and pan over a photo |
| `shake(t, t0, dur, amp, seed)` | an impact that settles; returns `{ x, y, r }` for `moveCamera` |
| `handheld(t, amp, seed)` | constant small drift, like a hand-held camera; goes to zero only if you fade `amp` out at the loop point |

## Texture and light

| Call | Effect |
|---|---|
| `grainLayer(opacity)` *markup* + `grain(t)` | film grain that changes every frame and still loops |
| `vignetteLayer(strength)` *markup* | darkened corners |
| `scanLayer(opacity)` *markup* + `scan(t)` | moving scanlines, for a screen or retro look |
| `leakLayer(rgb)` *markup* + `leak(t)` | a warm light leak drifting across the frame |
| `glitch(el, t, t0, dur, amount, seed)` | RGB split, jitter and slicing for a moment; put it on an inner element, it resets the transform when done |

Layers go last in the stage's markup so they sit on top of everything.

## Taste

- One signature effect per video carries more than five. Pick it in the brief and say why it fits the subject.
- In an app film the interface is the effect: no glitch, grain, glow, particles or confetti on the app itself. A
  sting, a title, a music video or an end card may use them.
- Effects mark moments: a glitch on a cut, confetti on the result, a shake on the drop. Constant effects (grain,
  vignette, leak) stay quiet: grain 0.08 to 0.15, leaks only on warm or nostalgic material.
- Text over footage sits on a plate (`.pill`) or a darkened band and stays readable at phone size.

## A new effect

Write it in the film's `scenes.js` as a function of `t` (and `hash` for anything random). If it would serve other
films, add it to `fx.js` and to this list in the same change, so the list stays the only thing anyone needs to read.
