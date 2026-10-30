# Desktop and camera

`device.js` in the desktop template draws one laptop display and everything on it, in **screen points** of a 14" laptop (1512 × 982): wallpaper, menu bar, dock, the app's window at `WIN`, and the pointer. Inside the window the app is laid out in **window points**, exactly as the app lays itself out. Around the display, an optional laptop: bezel, notch and a deck the lid closes onto.

## Parts

```js
desktopMarkup(appHtml, { name, menu, icon, dock, clock })  // the whole world, once, in build()
placeWorld(view, { rect, chrome, desk, hw, lid })            // every frame
placePointer(t, keys, clicks, on, off)                       // every frame
```

| Knob | 0 → 1 | Use |
|---|---|---|
| `rect` | a shape → `FULL` | the window grows out of a row, pill or card (and back) |
| `chrome` | none → shadow and traffic lights | after the window has its size |
| `desk` | window only → whole desktop | the pull-back: the desktop is revealed growing out from the window's edges |
| `hw` | bare display → laptop | bezel, notch and deck grow around the display |
| `lid` | closed → open | the only 3D in the kit; it has no transform while fully open, so the display stays crisp |

Until the pull-back the window floats on the film's canvas (`desk` 0), like the phone does in a mobile film: the app is the subject, the desktop is the reveal.

## Camera

`view(cx, cy, z)` puts screen point (cx, cy) at the stage centre at zoom z. `onWindow(x, y, z)` aims at a window point. `cameraAt(t, keys)` runs a list of `{ t, cx, cy, z }` keys, each added through its own spring (or `d` seconds of `E.smooth`), so a new move that starts before the last one lands never jerks. `toStage(view, x, y)` converts a screen point to stage pixels; use it to hand an object between the world and the stage (the closed laptop's deck becomes the row on the canvas).

- **Legibility first.** Desktop UIs are dense: 13–14 pt labels. On a 1440 square watched on a phone, frame so the text that matters is at least ~20 px: zoom 1.15–1.9 on the part of the window where the action is. Enlarge nothing inside the app; move the camera.
- **Whole window**: z ≈ 1.1 (1200-pt window). **A pane or list**: 1.15–1.4. **A dialog, palette or field being typed in**: 1.3–1.9. **Desktop**: 0.86. **Laptop**: 0.74.
- Never cut a label at the frame edge: either the whole row fits, or the crop falls in empty space.
- During a hold, add one slow key that eases the zoom in by 2–3 % over the hold, so a still screen never freezes.

## Pointer

`pointerAt(t, keys)` moves along a slight bow from wherever it was, easing into each key; `placePointer` shows it, presses it on each click time, and hides it outside `[on, off)`.

- Only when it explains an action: select, drag, click a control. Never wander, never idle-wiggle, never random.
- Arrive a beat early, click on the beat, let the result land before moving on.
- Hide it while the user types (macOS does), bring it back when the mouse is needed.
- Drags: the dragged thing lifts (shadow, slight shrink to a compact card) and follows the pointer's path exactly; on drop it shrinks into its target, and the target acknowledges (a count rolls, a row highlights once).
- Keyboard moments (⌘K, typing, Enter) show the keys' effect in the UI: letters appear at a typing pace (60–90 ms each), the matching result is highlighted, Enter presses the highlighted row.

## Window moves that read

- **Row → window**: a row (or pill) on the canvas is the window's `rect`; it expands to `FULL`, then chrome, then the app's parts assemble (sidebar slides, header rises, rows rise in with a stagger).
- **Split into panes**: a divider grows from the centre and the second pane slides in beside the first.
- **Card lifts into a preview**: the item's rect morphs into the preview's rect; closing folds it back into the same item.
- **Palette out of the search field**: the field's rect grows into the palette; Enter shrinks it into what it opened.
- **List swaps in place**: old rows leave (clip and slide, last first), new rows rise into the same slots; the title rolls.
- **Pull back**: desktop, then laptop; end by closing the lid into the row that opened the film.

## Platforms

If the app runs on Windows or Linux too, show the same window on each platform's desktop (same state, same place) changing only what the app itself changes there (caption buttons instead of traffic lights, drive and path strings). Draw desktops as simple stand-ins (wallpaper colour, taskbar or top bar); no OS logos, no other vendors' hardware.

## Capturing a real UI

When the app's interface is web technology (Tauri, Electron, a web app), capture the real UI instead of rebuilding it: see [capture](capture.md). Native apps are rebuilt from screenshots and their code, like mobile screens ([phone](phone.md), "Building a screen").
