---
name: i8-release-article
description: >
  Write the blog.infinito.nexus article for a release, its banner image for
  the Featured image, and the Mastodon and LinkedIn posts that announce it,
  from the changelog, in the blog's release style and a non-technical,
  feature-oriented voice for readers outside the project. Use when the
  operator asks for a release article, blog post, release banner or release
  announcement on social media. Infinito.Nexus specific.
routines:
  - release_article
---

Follow the instructions from AGENTS.md, then write the release article by
following the `release_article` routine exactly (run `python -m agents.routines show release_article` to print its ordered steps). That routine is the source
of truth; this skill only routes you there and ships the article and banner
templates under `templates/`. Begin by clarifying every open requirement with
the `active-listening` skill (release version, headline feature), then work
under the `robot` skill.
