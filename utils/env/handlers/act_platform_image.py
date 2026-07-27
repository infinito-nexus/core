"""ACT_PLATFORM_IMAGE: act runner platform image, resolved from the svc-runner
role's ``act-runner`` service declaration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.env.runtime import run_helper

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "ACT_PLATFORM_IMAGE"
COMMENT = (
    "act runner platform image, declared as svc-runner/act-runner in meta/services.yml."
)

RESOLVER = "scripts/meta/resolve/image/service_ref.sh"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    image = run_helper(
        ["bash", RESOLVER, "svc-runner", "act-runner", "upstream"],
        cwd=ctx.repo_root,
    )
    if image:
        eb.setdefault(KEY, image, comment=COMMENT)
