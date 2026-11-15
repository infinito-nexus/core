# Model Store

## Description

The model store holds every pinned model artefact of a host once, content-addressed under `<DIR_CACHE>/models/<sha256>`, so no AI engine downloads a model of its own and no file is held twice. The [Pinned Artefacts](../../docs/contributing/environment/cache.md#pinned-artefacts-) contract defines what may enter it.

## Overview

The role reads the artefacts the deployed roles declare under `cache: artefacts:` through the `cache_artefacts` lookup and fetches each digest once, through the package cache when `services.models.artefact_base` names its base, into the store. Every file is checked against its declared sha256 and size before it is renamed into place read-only; a mismatch fails the deploy naming the artefact, and a digest the store already holds intact is not fetched again. In swarm mode every node is seeded before any consumer starts, and a consumer whose artefact is missing on its node fails before it starts instead of downloading it.

An Argos package (`argos-net.com`) is also unpacked once into `argos-packages/<sha256>`, read-only, so LibreTranslate reads it through `ARGOS_PACKAGES_DIR` without unpacking it per container. Its manifest entry declares `unpacked_bytes`, the sum of the file sizes its archive lists; an archive listing any other sum fails the seed naming the artefact. A consumer that reads artefacts another role declares seeds them through `tasks/utils/seed.yml`.

The role runs no container. Its `min_storage` is the size of the store, every digest counted once, plus the `unpacked_bytes` of every Argos package, so the engines that read the store do not count it again.

## Features

- **One copy per digest:** Two names or roles declaring the same file share one store entry.
- **Verified before use:** Digest and size are checked on every fetch; a broken entry is fetched again, never served.
- **Idempotent:** A rerun on an intact store downloads, unpacks and hashes nothing: only verified files enter the store, read-only, so a held entry passes on its presence, size and mode. The `artefact_store` option `verify: full` re-hashes every entry for a manual check.
- **Swarm seeding:** Every swarm node holds the store before a consumer starts, so no node downloads on first use.
- **Fail before start:** A consumer that lacks an artefact on its node stops the deploy naming the artefact.
