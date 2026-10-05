# LibreTranslate Engine

This role deploys **LibreTranslate** as a plain translation engine, without a
public vhost, reverse proxy, MCP adapter or analytics. Callers reach it over
the container network and talk to its HTTP API directly.

Use `web-svc-libretranslate` instead when the deployment needs a public
domain, single sign-on, CSP handling or the MCP adapter.

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
| `directions` | `both` or `from_source` |
| `gpu` | run on CUDA and assert the device arrived |
| `ports.local.http` | host-bound port |

### loading_model

| value | when models arrive | cost |
| --- | --- | --- |
| `lazy` (default) | the served container fetches one the first time a request needs it | no build and no deploy wait; the first request for a pair pays for it |
| `build` | baked into the image | the build downloads every selected model, 13 GB for the full set; later requests never wait |
| `task` | a post-deploy task installs them into the running container | the deploy waits instead of the build, and an image rebuild does not refetch |

Under `lazy` and `task` the models live on a node-local bind mount, so a
rebuild or a recreate finds what an earlier run already fetched. `build` is
mounted without it, because a bind is never seeded from the image and would
hide what the build baked.

## GPU

With `gpu: true` the role builds the `-cuda` image and, when the host
exposes `/dev/nvidia0`, asserts after the deploy that CTranslate2 counts at
least one CUDA device. A host without the device builds the CPU image and
skips the assertion.
