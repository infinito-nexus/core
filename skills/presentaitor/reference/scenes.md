# Scene library

Read at the concept step of every chapter. Propose a set of scenes per chapter from this list, show it to the user, and let them swap, add or drop scenes before building. Every scene below exists as working code in `defaults/scenes/` (from the Stalwart demo series; its data is example data, replace it). Copy the functions you need into the film's `scenes.js` and restyle them from the project's brand tokens.

| Scene | What it shows | Best for | Example code |
|---|---|---|---|
| Title build | logo or glyph, kicker, title types or scrambles in, underline draws | chapter openers | `defaults/brand/example-intro-scenes.js` (s1), `explainer-address-path-split.js` (title) |
| Before / after snap | an old phrase sits loose and tilted, snaps into the new one on the beat | "until now… now it's built in" | `example-intro-scenes.js` (s2) |
| Object grows into object | an icon (envelope) grows into a system box with a typed label | introducing a component | `example-intro-scenes.js` (s3) |
| Feature tiles | 3 tiles land on the beat, then join under one bar or lock | listing what you get | `example-intro-scenes.js` (s4) |
| Big reveal | one word on the drop with shake and glitch | product or feature name | `example-intro-scenes.js` (s5) |
| Chapter strip | chips light up as the narrator names them | series overview, agenda | `example-intro-scenes.js` (s6) |
| Identifier card | a long identifier (address, key, URL) types in, tags land on the beat, a prefix springs in | explaining what something is | `explainer-address-path-split.js` |
| Path animation | an object travels from node A through hops to node B along a drawn route | data, mail or request flow | `explainer-address-path-split.js` |
| Split screen | two frozen or playing footage panels side by side with labels and chips | "sent" vs "arrived", before vs after | `explainer-address-path-split.js` |
| Terminal rebuild | a real log replayed in a styled terminal, slowing at key lines with a step card | deploys, CLI work, anything too fast to read | `terminal-rebuild-checklist.js` |
| Recap checklist | items check off one per beat | what one action gave you | `terminal-rebuild-checklist.js` |
| Footage highlights | rings and pills on real UI elements, freeze while each is explained, plates covering what must not show | walkthroughs over recordings | `footage-highlights.js` |
| Flow with switch | two systems side by side, a config switch flips, items flow across, a loop arrow for "repeatable" | migrations, imports, syncs | `migration-flow-endcard.js` |
| Warning card | a "before you start" card with chips | breaking changes, prerequisites | `migration-flow-endcard.js` |
| End card | NEXT card or closing line, logo, music credit, fade to canvas | every chapter end; series end | `terminal-rebuild-checklist.js` (s3), `migration-flow-endcard.js` |
| Title card | "CHAPTER NN" kicker and the chapter title rising word by word (`reveal` preset), logo, for 2.5 s in the series brand | between chapters of the long video only; `film.py join` makes one per chapter from the chapter's `film.css` and `assets.js` and its `voiceover.json` `"title"` | `title-card.js` |

## Motion presets

Build motion from the presets in `engine/templates/shared/presets.js` (table and calls in `SKILL.md`, section 3): `reveal` for text, `focus` for the camera, `cursor`, `captions`, `spotlight`, `emphasize` for a callout tied to a line, `morph` and `transition("whip")` between states and shots, `parallax`, `tilt`, `chart`, `aurora`, `motionBlur`, `rackFocus`. Time them with `line(id)` and `scene(id)` so they follow the voice, for example `emphasize(t, "n05", rect, "TLS included")` or `reveal(words, t, line("n01").start)`.

## Picking scenes

- One scene per idea; a chapter of 60-90 s usually has 3-5 scenes plus an end card.
- Explain, then show: a short motion scene that explains the idea, then the footage that proves it, then a recap.
- Put the biggest reveal on a musical drop (`music_edit.py` prints where drops land).
- Footage scenes keep the real UI legible: plates over empty space, never over what is being explained.
