# Phone and camera

`device.js` in the mobile template draws one iPhone (402 × 874 pt screen, iPhone 16 Pro / 17 Pro) and places it with one camera. Everything inside the screen is laid out in app points, exactly as the app's code lays it out; the camera scales the whole phone onto the stage.

## Anatomy

```js
const PHONE = { W: 402, H: 874, R: 55, bezel: 5, frame: 3 };
deviceMarkup(appHtml)   // shadow, side buttons, titanium body, bezel, screen (the app, then the overlay)
placeDevice(cam, rect, edge, buttons)
```

- **Overlay** (above the app, inside the screen): status bar (9:41, signal, battery), Dynamic Island (125 × 37 pt at y 11), home indicator (134 × 5 pt at y 861). They take `--sb`: set it to white over dark screens (camera, wallpaper, dark sheets): `$.overlay.style.setProperty("--sb", "#fff")`. Hide the home indicator on the Home Screen.
- **`rect`** is the lit part of the screen in app points: `FULL` normally; a small dot or band while the screen opens; the icon's rect while it closes onto an icon. The body, bezel, shadow and buttons follow it.
- **`edge`** 0 → 1 grows the frame and bezel around the rect; **`buttons`** 0 → 1 the side buttons. Grow them after the screen has opened; shrink them before it closes.

## Building a screen

1. Take 3× screenshots of each screen in the Simulator (`xcrun simctl io booted screenshot`), with fictional data seeded the way the app's own import or debug tools allow.
2. Read the screen's code for its spacing, type sizes, weights, colours, corner radii and copy. Where code and screenshot disagree, the screenshot wins (it is what ships).
3. Rebuild it in HTML inside `deviceMarkup`, absolutely positioned in points. Keep each piece that moves as its own element with a `data-k` key.
4. Overlay the screenshot at 50 % opacity during building to check alignment; remove it before QA.

Use the app's font (packed with `assets.py --font`) and its SF Symbols at the app's weights (`symbols.swift`, then `assets.py --sym`).

## Camera

A camera is `{ s, x, y }`: screen point (px, py) lands on the stage at (x + px·s, y + py·s).

- `camAt(s, top)` centres the phone horizontally and puts screen y `top` at the stage's top edge (a negative `top` leaves room above the phone).
- `cameraAt(shots, t)` runs a list of shots `{ t0, d, cam, rest }`: each eases (`E.smooth`) from wherever the previous one has drifted to; `rest` is when drifting starts.
- Keep the phone recognisable: both side edges in frame (at 1440 wide that is `s ≤ 3.3`); crop only top and bottom in close-ups.
- Readable text: 13 pt app text needs `s ≥ 1.55` to be about 20 px on stage. Frame the part of the screen that matters instead of showing the whole phone small.
- Scales that worked on a 1440 square: whole phone ≈ 1.5; a card or form ≈ 1.8–2.2; phone beside a caption ≈ 1.2.
- One move at a time; no camera moves during a tap or a transition inside the app.

## The Home Screen

When the story leaves the app (a widget, a notification, the icon), build a Home Screen: wallpaper (a soft gradient in the brand colours, never a photo), a grid of neutral placeholder icons with the app's real icon among them, widgets at their real sizes with the film's fictional numbers. White status bar, no home indicator. The app opens from and closes into its icon's rect.

## Endings

- **Close onto the icon**: `rect` morphs `FULL → icon rect` while the camera brings the icon's centre to the stage centre at its final pixel size, `edge` and `buttons` shrink to 0, and the icon art opens inside as a circle clip. Then the icon can become the brand dot, and the dot returns to the wordmark for the loop.
- **Pull back**: the camera eases out to the whole phone beside the wordmark and slogan.

## Don'ts

- App UI outside the phone, full-bleed.
- A phone floating at an angle, 3D tilts, reflections, glow, glass.
- Stock photos, hands, or real people's faces; a real person's name or number on screen.
- A different device mid-film.
