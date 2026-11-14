"""Compose the `.env` value-set from static defaults plus runtime context.

Thin orchestrator: each variable's mapping/computation lives in its own
module under :mod:`utils.env.handlers`. ``build_env`` walks the
``ORDERED_HANDLERS`` registry, letting each handler read/write through
an :class:`~utils.env.context.EnvBuilder`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import ORDERED_HANDLERS, docker_platform, ip_range
from utils.env.runtime import detect_gha_act

if TYPE_CHECKING:
    from pathlib import Path


def apply_custom_env(eb: EnvBuilder, repo_root: Path) -> None:
    """Overwrite every key found in ``<repo_root>/custom.env``.

    ``custom.env`` is the operator's untracked override file; its values
    win over static defaults AND handler-computed values.
    """
    from utils.env.parser import parse_static_env_with_comments

    custom_path = repo_root / "custom.env"
    if not custom_path.is_file():
        return
    custom, custom_comments = parse_static_env_with_comments(custom_path)
    for key, value in custom.items():
        eb.set(key, value)
        eb.comments[key] = custom_comments.get(key) or eb.comments.get(key, "")


def build_env(
    static: dict[str, str],
    repo_root: Path,
    *,
    comments: dict[str, str] | None = None,
) -> EnvBuilder:
    """Compose the full env-set from ``static`` (parsed default.env) +
    runtime context resolved against ``repo_root``.

    ``comments`` is the parsed per-key comment map from default.env
    (see :func:`utils.env.parser.parse_static_env_with_comments`).
    Dynamic keys carry their comments via each handler's ``COMMENT``
    constant. ``custom.env`` overrides run after every handler (see
    :func:`apply_custom_env`); only ``INFINITO_IP_RANGE`` is derived after
    them, because it follows the final ``INFINITO_SUBNET`` a worktree pins
    there.
    """
    on_gha, on_act = detect_gha_act()
    ctx = BuildContext(
        static=static,
        static_comments=comments or {},
        repo_root=repo_root,
        on_gha=on_gha,
        on_act=on_act,
    )
    eb = EnvBuilder()
    for handler in ORDERED_HANDLERS:
        handler.apply(eb, ctx)
    apply_custom_env(eb, repo_root)
    docker_platform.apply(eb, ctx)
    ip_range.finalize(eb)
    return eb
