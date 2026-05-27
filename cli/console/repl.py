"""Interactive REPL that forwards each input line to ``python -m cli`` on the host.

Ctrl+C only cancels the current input; the console exits on ``exit``/``quit`` or EOF (Ctrl+D).
Ctrl+Shift+C is intercepted by the terminal emulator (copy shortcut) and never reaches the app.

The prompt tracks a category stack: typing a bare category name cd's into it,
``..`` walks one level up, ``/`` returns to root, path tokens with ``/`` or
``..`` navigate, ``infinito [path]`` jumps absolute, ``ls`` lists the current
folder, everything else runs with the current path prepended.
"""

from __future__ import annotations

import contextlib
import shlex
import sys

from .banner import print_banner as _print_banner
from .constants import (
    AUTHOR,
    AUTHOR_URL,
    CLI_ROOT,
    DOCS_URL,
    EXIT_TOKENS,
    HELP_ALIASES,
    LICENSE_NAME,
    LICENSE_URL,
    LS_DESC_LIMIT,
    LS_TOKEN,
    PROMPT_PREFIX,
    ROOT_NAV_TOKEN,
    STRIPPABLE_PREFIXES,
    WEB_URL,
)
from .ls import do_ls as _do_ls
from .navigation import (
    is_category as _is_category,
)
from .navigation import (
    is_navigation_token as _is_navigation_token,
)
from .navigation import (
    normalize as _normalize,
)
from .navigation import (
    prompt as _prompt,
)
from .navigation import (
    resolve_argv as _resolve_argv,
)
from .navigation import (
    resolve_cd as _resolve_cd,
)
from .runner import (
    run_cli as _run_cli,
)

with contextlib.suppress(ImportError):
    import readline  # noqa: F401

# Re-exports + the test surface stays addressable as `repl.<symbol>`.
__all__ = [
    "AUTHOR",
    "AUTHOR_URL",
    "CLI_ROOT",
    "DOCS_URL",
    "EXIT_TOKENS",
    "HELP_ALIASES",
    "LICENSE_NAME",
    "LICENSE_URL",
    "LS_DESC_LIMIT",
    "LS_TOKEN",
    "PROMPT_PREFIX",
    "ROOT_NAV_TOKEN",
    "STRIPPABLE_PREFIXES",
    "WEB_URL",
    "main",
]


def main() -> int:
    _print_banner()
    current: list[str] = []
    while True:
        try:
            line = input(_prompt(current))
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            print()
            return 0

        stripped = line.strip()
        if not stripped:
            continue
        if stripped in EXIT_TOKENS:
            return 0

        try:
            argv = shlex.split(stripped)
        except ValueError as exc:
            print(f"console: parse error: {exc}", file=sys.stderr)
            continue

        head = argv[0]
        if head == LS_TOKEN and len(argv) == 1:
            _do_ls(current)
            continue
        if head == ROOT_NAV_TOKEN:
            target = "/" + "/".join(argv[1:]) if len(argv) > 1 else "/"
            resolved = _resolve_cd(current, target)
            if resolved is not None:
                current = resolved
            continue
        if len(argv) == 1 and _is_navigation_token(head):
            resolved = _resolve_cd(current, head)
            if resolved is not None:
                current = resolved
            continue
        if len(argv) == 1 and _is_category([*current, head]):
            current.append(head)
            continue

        _run_cli(_resolve_argv(current, _normalize(argv)), current=current)


if __name__ == "__main__":
    raise SystemExit(main())
