---
name: i8-release-mastodon
description: >
  Write the Mastodon release post from the release brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write the post as the `mastodon` step of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-post` method; this skill holds Mastodon's facts, and `i8-release` holds the brief and the voice.

## Channel

- [microblog.infinito.nexus](https://microblog.infinito.nexus/@kevinveenbirkenbach), posted with the banner PNG and its alt text.
- Read only `brief.yml`.
- Length: 470 to 500 characters as Mastodon counts them, every link as 23; the release posts 12.0 to 16.0 measure 471 to 500 on that count, and 500 is Mastodon's default limit.

## Post

- `mastodon.<language>.txt`, in this order:
  - an opening line with `Infinito.Nexus <major>.<minor>` and the headline benefit;
  - one paragraph of two or three sentences on what the headline benefit gives the reader;
  - one `Also new:` line on the rest of the release;
  - `Read before you upgrade:` on a major release;
  - the short link `links.article` of `brief.yml`, `https://s.infinito.nexus/infinito<major>`;
  - three to five CamelCase hashtags: `#InfinitoNexus`, `#SelfHosting`, `#OpenSource` and the headline technology.
- At most two emoji; plain and direct, no marketing superlatives.
- The operator creates the short link before posting.
