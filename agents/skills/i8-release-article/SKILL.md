---
name: i8-release-article
description: >
  Write the blog.infinito.nexus release article and its banner from the release brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write the article and the banner as the `article`, `theme` and `render` steps of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-article` method; this skill holds the blog's facts, and `i8-release` holds the brief and the voice.

## Channel

- [blog.infinito.nexus](https://blog.infinito.nexus/), category `Release`; the article is one WordPress Custom HTML block, the banner its Featured image and the image of the social posts.
- Read only `brief.yml`; the length bound comes from the blog's release posts, about 500 to 600 words of visible text, and the check enforces 500 to 600.

## Article

- Copy [templates/article.html](templates/article.html) to `article.<language>.html` and fill it in its order: badge; intro and a second paragraph; the warning on a major release only, otherwise drop the block; three feature cards; one or two sections on the headline benefit with a bold-lead list; the callout; Before You Upgrade with one "If you… / Then…" row per upgrade note, phrased as the action the reader takes; More Reliable with three or four fixes; Updated Applications with about thirteen chips from `updated_applications`, major versions first; the closing section.
- Repeat card, list item, table row and chip blocks as needed and remove every `{{…}}` placeholder.
- The title reads `<version>: <headline benefit>`; write it, the category and ten to twenty tags to `article-meta.<language>.txt`.

## Banner

- `python -m utils.design.film_theme --template agents/skills/i8-release-article/templates/banner.svg --out /tmp/release-<version>/banner.<language>.svg` fills the colours, fonts and logo from the design SPOT.
- Fill `{{VERSION}}`, two subtitle lines of at most 34 characters, four `{{ICON_n}}` 24 × 24 outline icons and four `{{LABEL_n}}` plain words of at most 14 characters for the headline benefits.
- Render it at 1500 × 1000 with the headless shell `make install-lint` provisions (`python -c "from utils.install.lint.mermaid_cli import browser_executable; print(browser_executable())"` prints its path): `<shell> --disable-gpu --hide-scrollbars --allow-file-access-from-files --window-size=1500,1000 --screenshot=/tmp/release-<version>/banner.<language>.png file:///tmp/release-<version>/banner.<language>.svg`; look at the PNG and fix overlaps or cut text.
- `banner-alt.<language>.txt` describes the banner in one to three sentences and repeats its title.

## Hand-over

Paste the whole article into one Custom HTML block and set the banner PNG as the Featured image; the banner never goes into the article HTML.
