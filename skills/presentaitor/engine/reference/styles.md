# Styles

A style is a whole decision: canvas, type, accent, how things move, what the camera does, and one signature move the film is remembered by. Offer the user two or three that suit the app (with a still of each rendered from the template), then build in one. The app's own UI is never restyled; a style dresses the stage around it.

Put the tokens in `film.css` (`:root`). Every style keeps the hard rules: real UI, deterministic, readable, the device always there.

## Brand-native

**When:** the app has a strong look of its own. Canvas, accent and type come straight from the app's tokens; the stage is its background colour, a shade lighter or darker.
**Motion:** whatever the app's own springs feel like (read its animation code). **Signature:** the app's most recognisable shape (a card, a bubble, a tab) carries the film from scene to scene.

## Meadow: soft and friendly

Example: `examples/rolyn` (mobile, personal finance).

```css
--bg: #F5F6F2; --ink: #151A16; --ink2: #4E574F; --accent: #2F7D32; --accentSoft: #E3F2E1;
--aura1: #D8F0D2; --aura2: #A6DB9B;
```
Rounded sans (the app's), large friendly numbers. Springs with a little overshoot (damping 0.8–0.88); things arrive from below and settle. The camera stays on the phone and eases in during holds. **Signature:** a brand dot that becomes the screen, the icon, and comes home to the wordmark.

## Warm ink: precise and tactile

Example: `examples/oryn` (desktop, file manager).

```css
--bg: #EEE9E1; --ink: #141416; --ink2: #6F6A62; /* accent: only where the app itself uses it */
```
Bold wordmark, clear interface labels, no decoration. Panels slide, rows assemble, selections travel; springs are firm (response 0.45–0.6, damping 0.84–0.9). Deliberate pointer moves only when they explain an action. **Signature:** shapes become windows. A row opens into the app, and a laptop lid closes into that row again.

## Midnight: focused and luminous

```css
--bg: #0D0F14; --ink: #F2F4F8; --ink2: #9AA3B2; --ink3: #5D6675; --accent: #8B7CFF; --accent2: #53E0B4;
```
Dark canvas, the app in its dark theme, light type with tabular numerals. The accent means one thing: *now* (the current time, the thing that just changed); new values arrive in the accent and cool to ink. Quick, clean moves (E.snappy, few overshoots), the camera glides in straight lines. Soft gradients on dark band in H.264: keep backgrounds flat, or render with `render.mjs video … --deband`, which dithers smooth areas as the video is encoded (never a per-frame noise in the film itself). **Signature:** a line of light (the "now" line) that runs through every scene.

## Field guide: earthy and editorial

```css
--bg: #EFE9DD; --ink: #1F2A22; --ink2: #56604F; --accent: #E0602B; --line: rgba(31, 42, 34, .18);
```
Paper canvas with contour lines drawn in `--line`; a serif for headlines beside the app's sans. Paths draw themselves along their length (`stroke-dashoffset` from t), numbers count, the camera follows a route. **Signature:** the route line. It draws the logo, runs across the map, and underlines the final line.

## Paper and ink: editorial, type-led

```css
--bg: #FFFFFF; --ink: #0E0E10; --ink2: #6B6B70; --accent: #FF4D2E;
```
White, near-black, one accent with one meaning. Between UI beats, a single oversized line (at most six words, 120–180 px, set tight) fills the frame; words land one per beat, space for each word reserved up front so the line never shifts. **Signature:** a punctuation mark (the accent full stop) that ends every line and becomes the logo's dot.

## Color block: bold and playful

```css
--bg: #FFD23F; --bg2: #3A86FF; --bg3: #FF5D8F; --ink: #111111;
```
The stage colour changes on bar lines (a wipe that follows the phone or window, never a cut to black) and the device sits on flat colour with a hard, offset shadow. Bouncier springs (damping 0.7–0.78), bigger scale moves, captions as stickers. **Signature:** every new scene's colour is the colour of the button that was just tapped.

## Choosing

| App | Good fits |
|---|---|
| finance, health, family | Meadow, Brand-native |
| developer, pro, productivity | Warm ink, Midnight |
| outdoors, travel, food | Field guide, Color block |
| community, games | Color block, Midnight |
| consumer launch, social | Color block, Paper and ink |
| design-led brand | Brand-native, Paper and ink |
