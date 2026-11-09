---
name: i8-release
description: >
  Turn a release's changelog into every announcement through one brief and the i8-release channel skills. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then work through the `release` routine (`python -m agents.routines show release` prints its steps) with the general `kvb-create-release` method; this skill holds the project facts that method needs.

## Release directory

- Every file goes to `/tmp/release-<version>/`, the changelog work to its `changelog/` folder.
- A channel text is named `<channel>.<language>.<ext>`, for example `mastodon.en.txt`, so the check finds it; any other text file there fails the check.
- No agent publishes or signs in anywhere; the hand-over lists every file and where it goes.

## Brief

- Without a `<version>` entry in `CHANGELOG.md`, run `i8-release-changelog` first and read its scratch copy.
- `python -m cli.contributing.release brief --version <version> --dir /tmp/release-<version> [--changelog <scratch copy>]` reads the entries since the last `vX.Y.Z` tag once into `brief.yml`: version, date, base tag, languages, the changelog lines by label, upgrade notes, updated applications, contributors and the links.
- You fill `headline` with the release's headline benefit and `benefits` with three to five entries of `title`, `text` and `changelog`, the lines they rest on copied verbatim; take the headline from the operator, otherwise from the largest `Added` line.
- Every channel skill reads `brief.yml` and its own channel facts only, never the changelog, so a claim the changelog does not carry cannot reach a channel.

## Languages

- Ask the operator once per release which languages to write and set `languages` in `brief.yml`; English alone is the default.
- WhatsApp keeps its own pair whatever the answer: the channel post in English, the personal message in German.

## Voice

The readers are outside the project, so every channel follows this voice unless its skill says otherwise.

- Feature-oriented: say what the reader gets and why it matters, not how it is built.
- No commands, flags, file paths, variable names, role names, inventory keys or code; product names, application names and version numbers are fine.
- Second person ("your servers"), present tense, short sentences, American English in English texts.
- Every claim traces back to `brief.yml`; no invented numbers, benefits or comparisons, and a beta feature says "beta".
- Section titles name a benefit; list items open with a bold benefit lead.
- No em dashes; hyphens only in compound words.

## Channels

| Channel | Skill |
|---|---|
| Changelog entry and `pkgmgr release` message | `i8-release-changelog` |
| Blog article and banner | `i8-release-article` |
| LinkedIn article and post | `i8-release-linkedin` |
| Mastodon post | `i8-release-mastodon` |
| WhatsApp channel post and personal message | `i8-release-whatsapp` |
| Newsletters for investors, customers and developers | `i8-release-newsletter` |
| Instagram image and caption | `i8-release-instagram` |

## Check and hand-over

- `python -m cli.contributing.release check --dir /tmp/release-<version> [--facts <facts file>]` MUST print no finding; it fails on an open brief, a leftover placeholder, an em dash, a length outside a channel's bounds, a number `brief.yml` and the facts file do not hold, and an investor section without evidence.
- Hand over the file list with the target of each file; the operator publishes.
