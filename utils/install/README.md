# utils/install

This directory hosts the Python implementation behind `make install-lint`, `make install-node` and `make install-codex`.
For the general rules that govern READMEs in code directories see [documentation.md](../../docs/contributing/documentation.md).

## Purpose

The package installs the lint toolchain (actionlint, shfmt, ruff, ansible-lint, mbake, markdownlint-cli2, eslint, shellcheck, ansible-playbook, ansible-galaxy) using the right channel per tool (system package manager, pip, npm, or GitHub release), and the tools a test suite needs beyond it (the Node.js runtime, the Codex CLI).
Modules at this level are channel-agnostic primitives or one tool with its own `make install-<tool>` target; lint toolchain policy lives one level down in [lint/](lint/).

## Structure

| File | Role |
|---|---|
| `primitives.py` | Logging, sudo wrapping, PATH mutation, and stdlib-based URL download. |
| `pip.py` | Venv-aware pip installer with `--break-system-packages` and `--user` fallback. |
| `npm.py` | Global / local npm install with per-user `--prefix` fallback. |
| `node.py` | Node.js runtime that is still supported upstream: the distro package, or the newest LTS from nodejs.org (signature- and checksum-verified) when the distro line has reached its end of life. |
| `codex.py` | Codex CLI at the package and version the `npm` update source of `roles/dsk-gnt-codex/meta/services.yml` pins, behind `make install-codex`, which [call-test.yml](../../.github/workflows/call-test.yml) runs before `make test` so the tests that drive the real client find it. |
| `github_release.py` | Latest-tag resolver and asset downloader for GitHub releases. |
| `system_pkg.py` | Per-manager dispatch for `pacman` / `apt-get` / `dnf` / `yum` / `brew`. |
| [`lint/`](lint/) | One module per tool, each exposing `ensure()`. See [lint README](lint/README.md). |

The CLI entry point lives at [__main__.py](lint/__main__.py), invoked from [lint.sh](../../scripts/install/lint.sh) as `python3 -m utils.install.lint`.
The matching dispatcher [wrapper.sh](../../scripts/install/wrapper.sh) routes `make install-lint` host vs container based on `INFINITO_LINT_RUNNER`.

## File Naming

- Module names MUST stay lowercase snake_case.
- Channel-agnostic helpers MUST live directly under `utils/install/`.
- A tool with its own `make install-<tool>` target MUST live directly under `utils/install/` as `<tool>.py`, one tool per file.
- Per-tool policy of the lint toolchain (one tool per file) MUST live under [`lint/`](lint/) (see [lint README](lint/README.md)).
- Test files live in `tests/unit/python/utils/install/` and mirror the module name with a `test_` prefix.

## Import Rules

- `primitives.py` MUST NOT import from any other module in this package.
- `pip.py`, `npm.py`, `github_release.py`, and `system_pkg.py` MAY import from `primitives.py`.
- `npm.py` MAY import from `system_pkg.py` and `node.py` to bootstrap npm itself; no other cross-imports between these four are allowed.
- `node.py` MAY import from `primitives.py` and `system_pkg.py`.
- `codex.py` MAY import from `npm.py` and `primitives.py`, takes its pin from `utils.update.source`, and imports `PROJECT_ROOT` from `utils` and the role file name from `utils.roles.mapping`.
- Per-tool modules under [`lint/`](lint/) MUST NOT import each other (see [lint README](lint/README.md)).
