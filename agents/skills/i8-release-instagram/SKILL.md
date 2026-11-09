---
name: i8-release-instagram
description: >
  Write the Instagram release image and its caption from the release brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then make the image and the caption as the `theme`, `instagram` and `render` steps of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-post` method; this skill holds Instagram's facts, and `i8-release` holds the brief and the voice.

## Channel

- One portrait image of 1080 × 1350 pixels with text, and a caption.
- Read only `brief.yml`.

## Image

- `python -m utils.design.film_theme --template agents/skills/i8-release-instagram/templates/instagram.svg --out /tmp/release-<version>/instagram.<language>.svg` fills the colours, fonts and logo from the design SPOT.
- Fill `{{VERSION}}`, two `{{HEADLINE_n}}` lines of at most 28 characters, three `{{BENEFIT_n}}` lines of at most 30 characters from `benefits`, three `{{ICON_n}}` 24 × 24 outline icons and `{{LINK}}` with `links.article` of `brief.yml` without its scheme; those limits keep the text inside the template.
- Render it like the banner, with `--window-size=1080,1350` and `instagram.<language>.png`, and look at the PNG.

## Caption

- `instagram-caption.<language>.txt`: at most 2,200 characters, Instagram's limit, with the first line of at most 125 characters, the part shown before "more".
- The headline benefit first, two or three short lines on what the reader gets, "link in bio" with the short link, since caption links are not clickable, then five to ten hashtags, at most 30.
