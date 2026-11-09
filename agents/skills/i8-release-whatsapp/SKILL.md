---
name: i8-release-whatsapp
description: >
  Write the English WhatsApp channel post and the German personal message of a release from its brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write both texts as the `whatsapp` step of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-post` method; this skill holds WhatsApp's facts, and `i8-release` holds the brief and the voice.

## Channel

- Two texts, whatever languages the release asks for: the channel post in English and the personal message in German.
- Read only `brief.yml`; send both with the banner PNG.
- Length: at most 500 characters each. No WhatsApp history exists to measure, so both keep the ceiling of the Mastodon post, which carries the same announcement.

## Channel post

- `whatsapp-channel.en.txt`: the Mastodon post's order without hashtags, since WhatsApp does not link them: the opening line with `Infinito.Nexus <major>.<minor>` and the headline benefit, one short paragraph, one `Also new:` line, the short link `links.article` of `brief.yml`.
- At most two emoji.

## Personal message

- `whatsapp-message.de.txt`: a short note in German, addressed with "du" as in a personal chat, on what the release gives the reader and the short link.
- No hashtags, no marketing tone.
