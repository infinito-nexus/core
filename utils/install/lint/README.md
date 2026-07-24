# utils/install/lint

Per-tool installer policy for the lint toolchain.
For the package's overall role see [README.md](../README.md).
For general README conventions see [documentation.md](../../../docs/contributing/documentation.md).

## Purpose

Each module in this directory owns exactly one lint tool and exposes a single `ensure()` function.
The CLI in [__main__.py](__main__.py) groups these ensure calls and applies the stamp-based skip for the default "all" invocation.

## File Naming

- A module name MUST match the lowercase snake_case of the tool it installs:
  - `actionlint` -> `actionlint.py`
  - `markdownlint-cli2` -> `markdownlint_cli2.py`
  - `ansible-lint` -> `ansible/lint.py`
- Aggregate installers (one helper covers a tightly coupled command pair) take the topic name without a key suffix.
  Example: `ansible/commands.py` installs both `ansible-playbook` and `ansible-galaxy` via the same system-package candidates.

## Module Shape

Every per-tool module MUST expose the same surface so the dispatcher can call it uniformly:

```python
"""<one-line docstring: what gets installed and via which channel>."""

from __future__ import annotations


def ensure() -> None:
    """Install <tool> if not present. Raises RuntimeError on failure."""
```

- `ensure()` MUST be idempotent: return immediately when the tool is already on PATH (or importable, for Python modules).
- `ensure()` MUST raise `RuntimeError` with a descriptive message on failure.
- A module MAY read tool-specific environment overrides (e.g. `ACTIONLINT_VERSION`, `RUFF_PIP_SPEC`) at call time.

## Import Rules

- A per-tool module MUST NOT import another per-tool module.
  Shared logic flows through `utils.install.primitives`, `utils.install.pip`, `utils.install.npm`, `utils.install.github_release`, and `utils.install.system_pkg` only.
- A per-tool module MAY import from `utils.cache` (for `PROJECT_ROOT`) and from stdlib.

## Group Dispatch

[__main__.py](__main__.py) maps each CLI group to a fixed set of `ensure()` calls:

| Group | Modules called (in order) |
|---|---|
| `action` | `actionlint` |
| `ansible` | `ansible_commands`, `ansible_collections`, `ansible_lint` |
| `python` | `shfmt`, `ruff` |
| `shellcheck` | `shellcheck` |
| `markdown` | `markdownlint_cli2` |
| `makefile` | `mbake` |
| `javascript` | `eslint` |
| `all` (default) | every group above, in the order listed |

The `all` mode honors a per-interpreter stamp at `build/install-lint-<hash>.stamp` (the suffix is the first 8 chars of `sha256(sys.executable)`, so host and container track independently even though `build/` is bind-mounted).
Stamp dependencies are [lint.sh](../../../scripts/install/lint.sh) and [pyproject.toml](../../../pyproject.toml).
Group-targeted invocations always run and never touch the stamp.
