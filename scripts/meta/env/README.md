# Environment Layer 🌍

This directory contains the shared environment bootstrap layer for Infinito.Nexus scripts. ✨

Its purpose is to keep runtime configuration centralized, deterministic, and easy to reuse across local runs, CI, and container-based execution. 🧭

The design follows simple composition principles so environment state can be loaded safely and consistently without duplicating logic in many places. 🧱

Use the directory-level entrypoint for sourcing this environment context in scripts and automation. ✅

## Modules 📦

The directory has two kinds of env modules:

- **Always-on modules** are composed by `all.sh` and SHOULD be sourced
  by anything that needs the standard project environment (Python
  interpreter, distro defaults, runtime context, inventory paths,
  GitHub markers): `python.sh`, `runtime.sh`, `defaults.sh`,
  `inventory.sh`, `github.sh`.
- **On-demand modules** MUST NOT be composed into `all.sh` because
  they encode an intent that only makes sense in a specific call
  path. The deploy-only marker is the canonical example:

  - `ci.sh` exports `INFINITO_MAKE_DEPLOY=1` so `MODE_CI` (defined in
    `group_vars/all/01_modes.yml`) flips to `true` for the duration
    of a make-driven deploy. It is sourced by every deploy
    entry-point under `scripts/tests/deploy/local/deploy/`. Sourcing
    it from `all.sh` would set the marker for unrelated `make test*`
    or `make build*` recipes too, which is exactly what
    [requirement 006](../../../docs/requirements/006-playwright-service-gated-tests.md)
    forbids.
