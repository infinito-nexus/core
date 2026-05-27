# utils/install

This directory hosts the Python implementation behind `make install-lint`.
For the general rules that govern READMEs in code directories see [documentation.md](../../docs/contributing/documentation.md).

## Purpose

The package installs the lint toolchain (actionlint, shfmt, ruff, ansible-lint, mbake, markdownlint-cli2, eslint, shellcheck, ansible-playbook, ansible-galaxy) using the right channel per tool (system package manager, pip, npm, or GitHub release).
Modules at this level are channel-agnostic primitives; per-tool policy lives one level down in [lint/](lint/).

## Structure

| File | Role |
|---|---|
| `primitives.py` | Logging, sudo wrapping, PATH mutation, and stdlib-based URL download. |
| `pip.py` | Venv-aware pip installer with `--break-system-packages` and `--user` fallback. |
| `npm.py` | Global / local npm install with per-user `--prefix` fallback. |
| `github_release.py` | Latest-tag resolver and asset downloader for GitHub releases. |
| `system_pkg.py` | Per-manager dispatch for `pacman` / `apt-get` / `dnf` / `yum` / `brew`. |
| `lint/` | One module per tool, each exposing `ensure()`. See [lint README](lint/README.md). |

The CLI entry point lives at [__main__.py](lint/__main__.py), invoked from [lint.sh](../../scripts/install/lint.sh) as `python3 -m utils.install.lint`.
The matching dispatcher [wrapper.sh](../../scripts/install/wrapper.sh) routes `make install-lint` host vs container based on `INFINITO_LINT_RUNNER`.

## File Naming

- Module names MUST stay lowercase snake_case.
- Channel-agnostic helpers MUST live directly under `utils/install/`.
- Per-tool policy (one tool per file) MUST live under `lint/` (see [lint README](lint/README.md)).
- Test files live in [tests/unit/utils/install/](../../tests/unit/utils/install/) and mirror the module name with a `test_` prefix.

## Import Rules

- `primitives.py` MUST NOT import from any other module in this package.
- `pip.py`, `npm.py`, `github_release.py`, and `system_pkg.py` MAY import from `primitives.py`.
- `npm.py` MAY import from `system_pkg.py` to bootstrap npm itself; no other cross-imports between these four are allowed.
- Per-tool modules under `lint/` MUST NOT import each other (see [lint README](lint/README.md)).
