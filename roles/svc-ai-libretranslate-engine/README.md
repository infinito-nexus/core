# LibreTranslate Engine

This role deploys **LibreTranslate** as a plain translation engine, without a
public vhost, reverse proxy, MCP adapter or analytics. Callers reach it over
the container network and talk to its HTTP API directly.

This is the only role that runs a LibreTranslate container.
`web-svc-libretranslate` adds a public domain, single sign-on, CSP handling
and the MCP adapter in front of it and forwards every request here, so the
deployment keeps one image, one model selection and one
`prefetch_models.py`. When the front's design is enabled, this role sets
the interface title to the front's design title.

## Description

LibreTranslate is an open-source machine translation API that can be
self-hosted. This role provides it as a backend other roles and build
pipelines call directly, such as the gettext catalog translation the `i18n`
make targets drive. Everything that exists only to serve a browser is left
out, so the image carries the engine and its models and nothing else.

## Overview

- Deployment via Docker Compose or Swarm
- No domain, no reverse proxy, no browser surface
- Host-bound port for local callers, container alias for in-stack callers
- Models arrive lazily, at build time or by a post-deploy task, selected per
  deployment

## Features

- Configurable container image and version
- Language selection via `services.libretranslate-engine.load_only`
- Direction selection via `services.libretranslate-engine.directions`, which keeps
  either every language pair or only those translating out of English
- Optional GPU execution, asserted after the deploy
- Package-cache CA installed into the build context
- Health check over the bundled interpreter

## Configuration

`meta/services.yml` carries the knobs:

| Key | Meaning |
| --- | --- |
| `image` / `version` | upstream image, suffixed `-cuda` when `gpu` is set |
| `load_only` | ISO 639-1 codes to load; empty means every package the engine offers |
| `loading_model` | when the models arrive: `lazy`, `build` or `task` |
| `model_store` | `true` reads the selected models from the model store; `false` keeps `loading_model` |
| `directions` | `both` or `from_source` |
| `gpu` | run on CUDA and assert the device arrived |
| `ports.local.http` | host-bound port |

### loading_model

| value | when models arrive | cost |
| --- | --- | --- |
| `lazy` (default) | the served container downloads the package index and every package between the `load_only` codes, both directions, when it starts with fewer than two installed; LibreTranslate filters by `load_only` only and ignores `directions` | no build; the first start downloads them before the engine serves, a later start finds them on the bind mount |
| `build` | baked into the image | the build downloads every selected model, 9 GB of archives unpacking to 10.3 GB for the full set, and keeps only the unpacked copy; later requests never wait |
| `task` | a post-deploy task installs them into the running container | the deploy waits instead of the build, and an image rebuild does not refetch |

Under `lazy` and `task` the models live on a node-local bind mount, so a
rebuild or a recreate finds what an earlier run already fetched. `build` is
mounted without it, because a bind is never seeded from the image and would
hide what the build baked.

With `model_store: true` and this role's `cache: artefacts:` covering the
selection, the [model store](../svc-ai-models/README.md) replaces every
`loading_model`: nothing is baked, installed or fetched lazily, the bind mount
is dropped, and only the selected packages are seeded and required. The
selection holds the pinned pairs between the `load_only` codes (every pair when
it is empty), only those out of `en` under `from_source`; it covers the request
when it holds at least two packages, every listed code is served and, under
`both`, every selected pair has its reverse. Below two installed packages
LibreTranslate fetches the package index and installs on every start, so a
single-package selection such as `from_source` with `load_only: [en, de]` keeps
its `loading_model`, as does every selection the pins do not cover. With the
defaults, `model_store: true` and `loading_model: lazy`, such a selection is not
seeded: LibreTranslate downloads the package index and every package between
the `load_only` codes, both directions, inside the container at start, as it
does without the store.
`ARGOS_PACKAGES_DIR` holds one read-only bind per selected package, so
`load_only` and `directions` keep their meaning although LibreTranslate applies
`load_only` only while fewer than two packages are installed. The MiniSBD
models, about 18 MB, are mounted whole.

The CI variants keep `model_store: false` for `build` and `task`, so those
paths stay deployed; `lazy` with the store off is covered only by the unit
render of `tests/unit/python/roles/svc-ai-libretranslate-engine/test_store_gate.py`,
since the lazy variant now runs the store. The same file proves that the
lazy path serves every selection the pins do not cover.

## GPU

With `gpu: true` the role builds the `-cuda` image and, when
`sys-svc-container` counts the host as a GPU host (see its README), asserts
after the deploy that CTranslate2 counts at least one CUDA device. Any other
host builds the CPU image and skips the assertion.
