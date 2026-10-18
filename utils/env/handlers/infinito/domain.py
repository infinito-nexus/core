"""INFINITO_DOMAIN: ``<stack>.<INFINITO_DNS_DOMAIN>``, where the stack is
``main`` for the primary checkout and the normalised branch for a linked git
worktree. Always overrides the caller env, which inside the stack container is
the previous ``.env``; GitHub/act runs keep the static default and custom.env
pins win."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import read_text

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_DOMAIN"
COMMENT = "Domain of this stack: <main|worktree branch>.INFINITO_DNS_DOMAIN."
PRIMARY_LABEL = "main"
MAX_LABEL_LENGTH = 63
_BRANCH_REF = "ref: refs/heads/"


def stack_label(repo_root: Path) -> str | None:
    """Return the DNS label of the stack that runs from ``repo_root``.

    Args:
        repo_root: the checkout the ``.env`` is generated for.

    Returns:
        ``main`` unless ``repo_root`` is a linked git worktree, whose branch is
        lowercased and every character outside ``[a-z0-9_-]`` replaced by
        ``-``; ``None`` when the worktree's git directory is not reachable,
        as inside a container that mounts only the checkout.
    """
    marker = repo_root / ".git"
    if not marker.is_file():
        return PRIMARY_LABEL
    gitdir = Path(read_text(str(marker)).strip().removeprefix("gitdir:").strip())
    head = (gitdir if gitdir.is_absolute() else marker.parent / gitdir) / "HEAD"
    if not head.is_file():
        return None
    branch = read_text(str(head)).strip().removeprefix(_BRANCH_REF)
    label = re.sub(r"[^a-z0-9_-]", "-", branch.lower()).strip("-")
    if not label or len(label) > MAX_LABEL_LENGTH:
        print(
            f"ERROR: worktree branch {branch!r} yields no DNS label of 1 to "
            f"{MAX_LABEL_LENGTH} characters (got {label!r})",
            file=sys.stderr,
        )
        sys.exit(2)
    return label


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if ctx.on_gha or ctx.on_act:
        return
    label = stack_label(ctx.repo_root)
    if label is None:
        print(
            f"WARNING: {ctx.repo_root} is a git worktree whose git directory is "
            f"not reachable here; {KEY} keeps {eb.get(KEY)!r} unless custom.env "
            "pins it",
            file=sys.stderr,
        )
        return
    eb.set(KEY, f"{label}.{eb.get('INFINITO_DNS_DOMAIN')}", comment=COMMENT)
