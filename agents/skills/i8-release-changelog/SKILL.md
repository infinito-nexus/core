---
name: i8-release-changelog
description: >
  Write a release's CHANGELOG.md entry on deterministic version jumps and contributors. Infinito.Nexus specific.
routines:
  - release
---

Follow the instructions from AGENTS.md, then write the entry as the `facts`, `prose` and `insert` steps of the `release` routine (`python -m agents.routines show release`) with the general `kvb-git-changelog` method, which also writes the `pkgmgr release` message; this skill holds the project's changelog facts.

## Facts before prose

- `python -m cli.contributing.changelog.extract facts --head <ref> --out /tmp/release-<version>/changelog [--base <tag>] [--repository infinito-nexus/core --logins <cache.json>]` writes `jumps.md` and `contributors.md` with their `.tsv` rows; the base is the last `vX.Y.Z` tag before the head.
- The version jumps come from the net diff between the base and the head across the role meta files, the Ansible collection requirements, `pyproject.toml` and the Dockerfiles under `roles/*/files`, renamed and added pins and versions inside URLs included, one line per role.
- The contributors come from `git shortlog -sne` over the range under `.mailmap`, co-author trailers counted, bots and coding assistants dropped; `--repository` resolves a missing GitHub login through `gh` and keeps it in the `--logins` cache, and a contributor without a login stays without a link.
- Copy both blocks into the entry; polish a pin's name into the product's name, merge lines that belong together, and never change a version.

## Entry

- `/tmp/release-<version>/changelog/entry.md` opens with `## [<version>] - <YYYY-MM-DD>` and holds, in this order and only when not empty: `Breaking:`, `Added:`, `Changed:`, `Fixed:`, `Version jumps (net since <base>):`, `Upgrade notes:`, `Contributors:`.
- One line per item as `- <Area>: <what changed>`, without a closing period; role names in `*italics*`.
- Each contributor line gets the person's areas of the range after a colon, read from their commits.
- `python -m cli.contributing.changelog.extract insert --entry /tmp/release-<version>/changelog/entry.md --out /tmp/release-<version>/changelog` puts the entry into a scratch copy of `CHANGELOG.md` under `lint/` and MUST end with markdownlint's `0 error(s)`; the repository's `CHANGELOG.md` stays untouched.
- Hand the entry to `kvb-git-changelog` for the `pkgmgr release` message; the operator releases.
