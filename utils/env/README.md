# utils/env 📐

This directory hosts the Python implementation behind `make dotenv`.
For the general rules that govern READMEs in code directories see [documentation.md](../../docs/contributing/documentation.md).
For the per-variable defaults that this code consumes see [default.env](../../default.env).

## Purpose 🎯

The package converts the committed [default.env](../../default.env) plus a small runtime context into the gitignored `.env` at the repo root.
Every module here belongs to one of four roles: parse, resolve, orchestrate, write.

## Structure 🗂️

| File | Role |
|---|---|
| `parser.py` | Read [default.env](../../default.env) into `(values, comments)` tuples. |
| `runtime.py` | Resolve host-context lookups (disk, RAM, hostname, GHA/Act flags, `/proc/version`, helper-script invocation). |
| `builder.py` | Thin orchestrator that defines `EnvBuilder`, `BuildContext`, and `build_env()`. Walks the handler registry. |
| `writer.py` | Serialise an `EnvBuilder` into a docker-compose-compatible `.env` on disk. |
| `handlers/` | One module per dynamically-computed variable. See [handlers README](handlers/README.md). |

The CLI entry point lives at [__main__.py](../../cli/meta/env/__main__.py) under `cli/meta/env/`.
Shell consumers source [load.sh](../../scripts/meta/env/load.sh) under `scripts/meta/env/`.

## File Naming 🏷️

- Module names MUST stay lowercase snake_case.
- Pure passthrough or simple parser/writer helpers MUST live directly under `utils/env/`.
- Per-variable computation MUST live under `handlers/` (see [handlers README](handlers/README.md) for the naming convention used there).
- Test files live in [tests/unit/python/utils/env/](../../tests/unit/python/utils/env/) and mirror the module name with a `test_` prefix.

## Machine Facts vs Run Facts 🧭

The writer a handler picks decides how long a value lives. Both kinds are registered in `default.env` and both are visible to the lints; they differ only in whether the generated `.env` remembers what the environment said.

| Writer | Meaning | On the next `make dotenv` |
|---|---|---|
| `eb.setdefault` | machine fact | a non-empty value in the process env is adopted and written back |
| `eb.set` | run fact | recomputed from `BuildContext`; whatever the process env said is discarded |

`setdefault` is the operator-override contract: exporting a key changes it and the change persists. That persistence is why it MUST NOT carry a value an environment declares for a single run. [Makefile](../../Makefile) exports `BASH_ENV`, so every make recipe sources `.env` — a value adopted once is re-exported into every later recipe and into every container that mounts the repo, and a per-run decision has silently become a property of the machine.

A key that some environment declares per run therefore MUST be written by a dedicated handler through `eb.set`. The exporting shell still wins for its own run, because [load.sh](../../scripts/meta/env/load.sh) preserves non-empty caller values when it sources `.env`; the file keeps the derived default. `INFINITO_RUNNING_ON_GITHUB` and `INFINITO_CACHE_STACK` are written this way. Note the consequence: for those keys `.env` and the running shell can legitimately disagree, and `.env` is not the authority.

## Import Rules 🔗

- `parser.py`, `runtime.py`, and `writer.py` MUST NOT import from `builder.py` or `handlers/`.
- `builder.py` MUST NOT import individual handler modules; it MUST go through the `ORDERED_HANDLERS` list exposed by `handlers/__init__.py`.
- Handler modules MUST NOT import each other (see [handlers README](handlers/README.md)).
