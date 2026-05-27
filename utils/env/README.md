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
- Test files live in [tests/unit/utils/env/](../../tests/unit/utils/env/) and mirror the module name with a `test_` prefix.

## Import Rules 🔗

- `parser.py`, `runtime.py`, and `writer.py` MUST NOT import from `builder.py` or `handlers/`.
- `builder.py` MUST NOT import individual handler modules; it MUST go through the `ORDERED_HANDLERS` list exposed by `handlers/__init__.py`.
- Handler modules MUST NOT import each other (see [handlers README](handlers/README.md)).
