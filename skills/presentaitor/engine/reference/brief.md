# The brief

Every new film starts with a brief written for this product alone, agreed with the user before anything is built. It is the plan: what the film is for, what it may use, how it should feel, the story scene by scene, how it is built, and what happens first.

## As a plan

Unless the user has asked you to go straight to building, or handed you a complete brief of their own, plan first ([harness](harness.md), "Plan"). While planning you only read: the code, the assets, the screenshots. Write the brief as the plan and present it for approval; build only after the user approves it. Save the approved brief as `brief.md` in the film folder, and keep to it. A change of direction is a change to the brief first.

## The product's name

The brief is written around the product's own name, spelled the way the product spells it. Take it from the first of these that answers:

1. what the user called it;
2. the app's own manifest: `CFBundleDisplayName` or `CFBundleName` (Info.plist, or `INFOPLIST_KEY_CFBundleDisplayName` / `PRODUCT_NAME` in the Xcode project) for Apple platforms; `app_name` in `res/values/strings.xml` for Android; `productName` in `tauri.conf.json` or `package.json` (then `name`) for Tauri, Electron and web apps; `name` in `app.json` (Expo), `pubspec.yaml` (Flutter) or `Cargo.toml`;
3. the README's title, or the site's `<title>`;
4. the folder's name, tidied (`ledger-app` → Ledger).

If sources disagree, or only the folder name is left, ask the user once, offering what you found. Never invent a name.

## Read the product first

- **What it does**, in one sentence, from its own words: README, onboarding, store text, empty states.
- **The moments worth filming**: three to five real flows, named as the app names them (screens, commands, buttons), found in the code and not guessed.
- **Its look**: colours from its theme or tokens, its fonts, the logo, the icon, its motion (springs, durations).
- **Its platform and form**: iPhone, desktop window, web page in a browser.
- **Its claims**: only what the code or its copy supports (see [rights](rights.md)).
- **What exists as material**: screenshots, recordings, a Simulator or desktop build, a running web frontend.

## The shape

Fill every part for this product; the example shows the shape, never lines to reuse.

```
<NAME>: <A PROMISE IN TWO TO FOUR WORDS, CAPS>

One short paragraph: the film, for which product, the feeling it should leave, and that it is built in
code, with no templates or stock motion graphics.

<inputs>
What the film uses: the logo and wordmark, screenshots or recordings of the named flows, the music (the user's
track, or an original made for the film), optional footage for the last shot. What to ask for if it is
missing. The real interface only, with no invented features and no redesign.
</inputs>

<direction>
The feel in the product's own terms. Canvas, ink and accent taken from its interface; type for the wordmark
and for interface labels. How each scene grows out of the one before, with the product's own shapes. When a
pointer or a finger appears, and why. Pacing. The sound: the music's role, tempo, texture and energy by scene,
and which actions make a sound ([music](music.md#0-the-sound-brief)). What to avoid.
</direction>

<structure>
Scene by scene: the opening, each named flow as one scene built from the last, the key result on the drop,
the pull-back, the closing line (new, short, in the product's voice) and how the last frame meets the first.
</structure>

<build>
The format (square 1440 × 1440, vertical 1080 × 1920 or landscape 1920 × 1080), every frame from a
deterministic seek(t), spring motion, the interface's source of truth, what lands on which beat, and the
60 fps render with what to inspect.
</build>

<start>
What to ask for first, then the beat map and four stills (named for this product's moments) and wait for
feedback before building the whole film.
</start>
```

The film's type decides the structure: a product film in a device, a story told by a character or a line of text, feature cards, a type-led film, a sting ([types](types.md)). Say which one in the paragraph.

## Make it this product's

- Name its features by their names in the app, its screens by their titles, its data by what it actually holds.
- Nothing carried over from another film: no borrowed taglines, scene ideas or closing lines, and that includes the example.
- Every scene shows the real product doing something; no scene exists only to look nice.
- If a sentence would fit any app, rewrite it until it fits only this one.

[An example of the shape](brief-example.md), written for a desktop file manager.
