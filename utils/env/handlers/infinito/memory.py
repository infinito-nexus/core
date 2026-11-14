from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.runtime import mem_total_mb

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEYS = ("INFINITO_MEM_LIMIT", "INFINITO_MEMSWAP_LIMIT")
STATIC_READS = KEYS
HOST_SHARE_PERCENT = 75


def host_share(ctx: BuildContext) -> str:
    """
    Args:
        ctx: the build context; GitHub Actions and act runs get no cap.

    Returns:
        ``HOST_SHARE_PERCENT`` of the host's MemTotal as a compose size such
        as ``49152m``, or an empty string on GitHub Actions, on act, or when
        MemTotal cannot be read.
    """
    if ctx.on_gha or ctx.on_act:
        return ""
    total = mem_total_mb()
    return f"{total * HOST_SHARE_PERCENT // 100}m" if total > 0 else ""


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    share = host_share(ctx)
    for key in KEYS:
        if share or key in ctx.static:
            eb.setdefault(
                key, share or ctx.static[key], comment=ctx.static_comments.get(key, "")
            )
