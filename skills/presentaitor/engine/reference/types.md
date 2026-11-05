# Film types

The brief names one type. All of them run on the same engine (one page, every frame from `seek(t)`, on the music's grid) and pass the same checks; what changes is the story's shape, the format and what fills the frame.

| Type | Best for | Length · format | Built from |
|---|---|---|---|
| Product film | showing the app itself working | 30–60 s · square or landscape | `templates/mobile`, `templates/desktop` |
| Story | a launch with a point of view: a problem, the product, what changes | 25–45 s · landscape, square or vertical | `templates/story` |
| Feature cards | several features, quickly, for a store page or a social post | 15–30 s · vertical or square | `templates/story` (panels only) |
| Type-led | a statement the app backs up; editorial brands | 15–30 s · any | `templates/story` (lines only) |
| Sting | an intro, an outro, a logo reveal | 3–8 s · any, loops | any template, one scene |

A **social cut** is any of these at 15–25 s in 1080 × 1920, with the strongest moment in the first two seconds.

## Product film

The app's real interface inside its device, one camera, every move on the beat: the wordmark becomes the app, the flows follow one another, the key result lands on the drop, the camera pulls back, and the last frame meets the first. The rest of this skill describes it in detail ([phone](phone.md), [desktop](desktop.md)).

## Story

A point of view in three acts, told by a narrator: a line of type, or the brand's character.

1. **Hook** (2–4 lines, 6–10 s): who is speaking and what is wrong. Each line is a short sentence that types in on the beat; one word in it carries the accent. A character, if there is one, acts every line.
2. **Arrival** (1–2 lines): the product appears with its wordmark and its real interface, in a phone or a window.
3. **Features** (3–5 scenes, 3–5 s each): each is a panel. A headline of four to eight words says what it does for the viewer, with one accent word; beside it the app's real interface (cards, a screen, a control) does exactly that, in motion (a toggle flips, a number counts, a line draws, a row lands). The character, small in a corner, reacts.
4. **End card**: logo and wordmark, the line with its accent word, a call to action (a button with the product's own words for it), the address, and three or four facts in small type. The last frame leads back into the first.

How it is built:

- **Accent words.** A headline's plain words are set in the display sans; the accent word is set apart (an italic serif, the brand's accent colour, a stroke drawn under it) and types in letter by letter after the rest has landed. One accent per line, never two.
- **Panels.** Each scene is a coloured field with rounded panels on it: a narrow one for the headline, a wide one for the interface. Scenes change colour on bar lines; a panel slides in from the side the story moves to, the next scene's panels push it out. Colours come from the brand, a pale tint of each.
- **Interface as cards.** The app's real components, rebuilt at a readable size: a list row, a balance, a chart, a toggle, a status pill. Each card does one thing on a beat; numbers roll, lines draw along their length, toggles spring.
- **Sound.** A quiet bed under the words, and a small sound on every action that matters: ticks as the accent types, a pop on each check, a whoosh on each wipe, a chime on the logo ([music](music.md#0-the-sound-brief)). The bed's breaks and lifts line up with the hook and the reveal.
- **No captions.** Nothing on screen but the headline, the interface and the character: no scene numbers, section names, timecodes or code-style labels in the corners.
- **The character.** The brand's mascot as art (an image or an SVG per pose) with simple acting (breathing, a blink, a hop, a lean toward what matters) large in the hook, small in a corner badge during the features, back beside the wordmark at the end. Never a stranger's character, and never one invented for a brand that has its own.

## Feature cards

A run of panels without the hook: each card is one feature (a headline with its accent word and the interface doing it) pushed in by the next on the beat. Ends on the logo card. Good as a 15–25 s vertical.

## Type-led

Lines of type do the telling: one oversized line fills the frame, a word per beat, space for each word held from the start so nothing shifts; between lines the interface proves the line in a single move. Ends on the wordmark. See Paper and ink in [styles](styles.md).

## Sting

One idea in 3–8 seconds: the wordmark builds from the icon, or a shape from the app becomes the logo, then the tagline. Cut to a whole number of bars so it loops.

## Beyond app films

The same engine makes any short video. Start these from `templates/blank` (a dark canvas with full-frame shots, any
size) or `templates/overlay` (a clear background drawn over footage), and reach for [effects](effects.md).

| Type | Best for | Length · format | Built from |
|---|---|---|---|
| Title or sting | an intro, outro, logo or channel open | 3–10 s · any | `blank`: one or two shots, `split` + `rise`, one signature effect |
| Kinetic type | a quote, a manifesto, an announcement | 10–40 s · vertical or square | `blank`: a line per beat, words with `stagger`, joins on bar lines |
| Explainer | a topic or an idea, often with a voiceover | 30–90 s · landscape or vertical | `blank`: one shot per point, diagrams with `drawPath`, numbers with `countUp`, [voiceover](voiceover.md) |
| Data video | a stat, a result, a chart | 8–30 s · any | `blank`: `countUp`, bars on `stagger`, lines with `drawPath` |
| Music video or lyric cut | a track the visuals follow | the track's length · any | `blank`: cuts and hits on the grid from [music](music.md), `shake`, `glitch`, `sweep` on the drops |
| Photo montage | photos telling a story | 15–60 s · any | `blank`: one photo per shot with `kenBurns`, `dissolve` or `push` joins |
| Overlay on footage | lower thirds, captions, callouts, end cards on a recording | the footage's length · the footage's format | `overlay`, rendered with `--under footage.mp4` |

How these differ from an app film:

- **The brief** still comes first ([brief](brief.md)): what the video says, to whom, in which order. Swap "the
  product's flows" for the points or lines it makes.
- **Shots.** Each shot is a full-frame layer; `sequence()` shows them in turn and plays the join. One idea per shot,
  each held long enough to read (the timing rule in [qa](qa.md)).
- **Footage.** The picture under an overlay is the user's file; the film only draws what goes on top. Preview with
  `render.mjs stills ... --under footage.mp4`, render with `render.mjs video ... --under footage.mp4 [--under-from s]`,
  and verify with the same `--under`. The footage's own sound is kept unless `--audio` replaces it.
- **Facts.** Numbers, quotes and names are the user's or invented for a demo, and the brief says which.
