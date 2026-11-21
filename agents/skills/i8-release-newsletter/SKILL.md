---
name: i8-release-newsletter
description: >
  Write the investor, customer and developer newsletters of a release as listmonk campaigns from its brief. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write the three newsletters as the `outline` and `newsletter` steps of the `release` routine (`python -m agents.routines show release`) with the general `kvb-create-article` method; this skill holds the newsletters' facts, and `i8-release` holds the brief and the voice.

## Channel

- One [listmonk](../../../roles/web-app-listmonk/README.md) campaign per audience, content type Markdown; the operator pastes the subject, the preheader and the body.
- `newsletter-investors.<language>.md`, `newsletter-customers.<language>.md` and `newsletter-developers.<language>.md`: a `Subject:` line, a `Preheader:` line, an empty line, then the Markdown body.
- Read only `brief.yml`, and for investors also the facts file.
- Length: subject at most 60 characters, where desktop mail clients cut it; preheader at most 130, the most a client previews; body at most 600 words, the blog article's ceiling, since every newsletter points to the article. No campaign history exists to measure, so these are the clients' limits, not measurements.

## Investors

- Only what the repository proves through `brief.yml`, plus figures from a facts file the operator passes; the facts file stays outside the repository and is never committed.
- `python -m cli.contributing.release outline --dir /tmp/release-<version> [--facts <facts file>]` writes `investor-outline.yml`, the sections with evidence in this order: The Release, Product Progress, Ecosystem and Community from the brief; Adoption, Revenue, Funding and Outlook from the facts file's top-level keys `adoption`, `revenue`, `funding` and `outlook`.
- Each section is one `##` heading with that exact title; a section without evidence is left out, never filled with a placeholder or an estimate, and the check fails on its heading.
- Every figure names its source as the facts file states it.

## Customers

The voice of `i8-release`: what the release gives the people who use the apps, the upgrade notes as actions, the article link.

## Developers

- The technical view the other channels leave out: the breaking changes and upgrade notes in full, the version jumps of `updated_applications`, the contributors with their profiles, the repository and changelog links of `brief.yml`.
- Role names and versions are fine here; commands stay in the changelog.
