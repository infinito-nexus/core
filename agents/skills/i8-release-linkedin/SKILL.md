---
name: i8-release-linkedin
description: >
  Write the LinkedIn company-page article and the post that links it from the release brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write both texts as the `linkedin` step of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-article` method for the article and `kvb-create-post` for the post; this skill holds LinkedIn's facts, and `i8-release` holds the brief and the voice.

## Channel

- The Infinito.Nexus [company page](https://www.linkedin.com/company/107414216/); the article goes out under the page, the post links it.
- Read only `brief.yml`.
- LinkedIn allows no anonymous read access, so no length below is measured on the page; the bounds are the release standard the earlier LinkedIn release posts were written to, and the article mirrors the blog article's length.

## Article

- `linkedin-article.<language>.md`: the blog article's title and content as Markdown for LinkedIn's article editor, 500 to 600 words, the banner PNG as its cover image.
- Same structure as the blog: lead, the headline benefit with a bold-lead list, before you upgrade, more reliable, updated applications, closing with the links of `brief.yml`.

## Post

- `linkedin-post.<language>.txt`: 1,000 to 1,600 characters.
- A hook in the first line of at most 200 characters, since LinkedIn shows only the first lines before "see more".
- Then short paragraphs: what the headline benefit gives an organization, three benefit lines each opened by one emoji, one paragraph on the rest of the release, the upgrade pointer, the article link, and three to five hashtags.
- Professional tone, second person, no hype words.
