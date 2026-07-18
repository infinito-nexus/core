"""CLI entry point for ``python -m utils.install.lint``.

Mirrors the prior ``scripts/install/lint.sh`` interface: no-arg / ``all``
runs every group + manages the stamp file; explicit groups bypass the
stamp; ``--force`` (as first arg) drops the stamp and reinstalls.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sys
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.install.lint import (
    actionlint,
    eslint,
    hadolint,
    markdownlint_cli2,
    mbake,
    mermaid_cli,
    packages,
    playwright,
    ruff,
    shellcheck,
    shfmt,
)
from utils.install.lint.ansible import collections as ansible_collections
from utils.install.lint.ansible import commands as ansible_commands
from utils.install.lint.ansible import lint as ansible_lint
from utils.install.primitives import warn

_STAMP_KEY = hashlib.sha256(sys.executable.encode("utf-8")).hexdigest()[:8]
_STAMP = f"build/install-lint-{_STAMP_KEY}.stamp"
_STAMP_DEPS = (
    "scripts/install/lint.sh",
    "pyproject.toml",
)

_STAMP_TOOLS = (
    "actionlint",
    "ansible-lint",
    "ansible-playbook",
    "eslint",
    "hadolint",
    "markdownlint-cli2",
    "mbake",
    "ruff",
    "shellcheck",
    "shfmt",
)


def _install_action_tools() -> None:
    actionlint.ensure()


def _install_ansible_tools() -> None:
    ansible_commands.ensure()
    ansible_collections.ensure()
    ansible_lint.ensure()


def _install_python_tools() -> None:
    shfmt.ensure()
    ruff.ensure()


def _install_shellcheck_tools() -> None:
    shellcheck.ensure()


def _install_dockerfile_tools() -> None:
    hadolint.ensure()


def _install_markdown_tools() -> None:
    markdownlint_cli2.ensure()


def _install_mermaid_tools() -> None:
    mermaid_cli.ensure()


def _install_makefile_tools() -> None:
    mbake.ensure()


def _install_javascript_tools() -> None:
    eslint.ensure()


def _install_playwright_tools() -> None:
    playwright.ensure()


def _install_packages_tools() -> None:
    packages.ensure()


_GROUP_FN_NAMES = {
    "action": "_install_action_tools",
    "ansible": "_install_ansible_tools",
    "python": "_install_python_tools",
    "shellcheck": "_install_shellcheck_tools",
    "dockerfile": "_install_dockerfile_tools",
    "markdown": "_install_markdown_tools",
    "mermaid": "_install_mermaid_tools",
    "makefile": "_install_makefile_tools",
    "javascript": "_install_javascript_tools",
    "playwright": "_install_playwright_tools",
    "packages": "_install_packages_tools",
}


def _install_all() -> None:
    _install_action_tools()
    _install_ansible_tools()
    _install_python_tools()
    _install_shellcheck_tools()
    _install_dockerfile_tools()
    _install_markdown_tools()
    _install_mermaid_tools()
    _install_makefile_tools()
    _install_javascript_tools()
    _install_playwright_tools()


def _stamp_is_fresh(repo_root: Path) -> bool:
    stamp_path = repo_root / _STAMP
    if not stamp_path.is_file():
        return False
    stamp_mtime = stamp_path.stat().st_mtime
    for dep in _STAMP_DEPS:
        dep_path = repo_root / dep
        if not dep_path.is_file():
            warn(f"[install-lint] missing dependency: {dep}")
            return False
        if dep_path.stat().st_mtime > stamp_mtime:
            return False
    return all(shutil.which(tool) is not None for tool in _STAMP_TOOLS)


def _touch_stamp(repo_root: Path) -> None:
    stamp_path = repo_root / _STAMP
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(PermissionError):
        stamp_path.parent.chmod(0o777)
    stamp_path.touch()


def _dispatch(group: str) -> None:
    if group == "all":
        _install_all()
        return
    fn_name = _GROUP_FN_NAMES.get(group)
    if fn_name is None:
        raise RuntimeError(
            "Usage: python -m utils.install.lint "
            "[all|action|ansible|python|shellcheck|dockerfile|markdown|mermaid|makefile|javascript|playwright|packages]..."
        )
    globals()[fn_name]()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path(PROJECT_ROOT)

    force = False
    if args and args[0] == "--force":
        force = True
        stamp_path = repo_root / _STAMP
        if stamp_path.exists():
            stamp_path.unlink()
        args = args[1:]

    if not args:
        args = ["all"]

    is_all_mode = len(args) == 1 and args[0] == "all"

    if is_all_mode and not force and _stamp_is_fresh(repo_root):
        return 0

    # chdir for installers that resolve relative paths (eslint's npm ci
    previous_cwd = Path.cwd() if Path.cwd().exists() else None
    os.chdir(repo_root)
    try:
        for group in args:
            _dispatch(group)
    except RuntimeError as exc:
        warn(str(exc))
        return 1
    finally:
        if previous_cwd is not None and previous_cwd.exists():
            os.chdir(previous_cwd)

    if is_all_mode:
        _touch_stamp(repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
