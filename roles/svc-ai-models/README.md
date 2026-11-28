# Model Store

## Description

The model store holds every pinned model artefact of a host once, content-addressed under `<DIR_CACHE>/models/<sha256>`, so no AI engine downloads a model of its own and no file is held twice. The [Pinned Artefacts](../../docs/contributing/environment/cache.md#pinned-artefacts-) contract defines what may enter it.

## Overview

The role reads the artefacts the deployed roles declare under `cache: artefacts:` through the `cache_artefacts` lookup, leaves out the Argos packages and MiniSBD models, which each LibreTranslate consumer seeds as its own selection, and fetches each remaining digest once into the store, under the base `services.models.artefact_base` names. The role leaves it empty, which fetches from the upstream; the development inventory sets it to `INFINITO_ARTEFACT_BASE`, the package cache frontend while the cache stack runs. `tasks/utils/seed.yml` fetches every record under that base, whichever role looked it up. Every file is checked against its declared sha256 and size before it is renamed into place read-only; a mismatch fails the deploy naming the artefact, and a digest the store already holds intact is not fetched again. In swarm mode every node a consumer can be placed on is seeded before any consumer starts, and a consumer whose artefact is missing on its node fails before it starts instead of downloading it.

An Argos package (`argos-net.com`) is also unpacked once into `argos-packages/<sha256>`, read-only, so LibreTranslate reads it through `ARGOS_PACKAGES_DIR` without unpacking it per container. Its manifest entry declares `unpacked_bytes`, the sum of the file sizes its archive lists; an archive listing any other sum fails the seed naming the artefact. A consumer that reads artefacts another role declares seeds them through `tasks/utils/seed.yml`.

The role runs no container. Its `min_storage` is the size of what it seeds, every digest counted once, plus the `unpacked_bytes` of every Argos package among them, so the engines that read the store do not count it again. It is the static sum over every declared artefact except the Argos packages and MiniSBD models it leaves to the LibreTranslate consumers, so it overstates a host that deploys only some of their consumers. No `min_storage` counts a LibreTranslate selection: its size follows the consumer's `load_only` and `directions`, which a static value cannot, from about 650 MB for two languages in both directions to about 19 GB for every pinned pair. Before the store, the container downloaded the same packages, which no `min_storage` counted either.

## Features

- **One copy per digest:** Two names or roles declaring the same file share one store entry.
- **Verified before use:** Digest and size are checked on every fetch; a broken entry is fetched again, never served.
- **Idempotent:** A rerun on an intact store downloads, unpacks and hashes nothing: only verified files enter the store, read-only, so a held entry passes on its presence, size and mode. The `artefact_store` option `verify: full` re-hashes every entry for a manual check.
- **Swarm seeding:** Every swarm node holds the store before a consumer starts, so no node downloads a seeded artefact on first use. A `svc-virt-kata` sandbox node (a member of that group outside `svc-swarm-manager`, which the sandbox role labels) is left out: every service that is not sandboxed itself is placed off the sandbox label, so no store consumer can run there. One play host seeds every node in turn, since the store takes one writer at a time. A LibreTranslate selection the store does not cover (fewer than two packages, a language without a pinned package, or a pair under `both` without its reverse) is not seeded: with the default `model_store: true` the engine falls back to its `loading_model`, by default `lazy`, and LibreTranslate downloads the package index and packages inside the container when it starts. `web-svc-libretranslate` runs no LibreTranslate of its own and forwards to the engine, so this lazy path serves its uncovered selections too.
- **Fail before start:** A consumer that lacks an artefact on its node stops the deploy naming the artefact.
