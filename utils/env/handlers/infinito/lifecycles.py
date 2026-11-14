from __future__ import annotations

from typing import TYPE_CHECKING

from utils.roles.lifecycle import CI_DEPLOY, FILE_META_LIFECYCLE, default_envelope, load

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "INFINITO_LIFECYCLES"
COMMENT = (
    "Lifecycles CI deploy discovery covers (apps.sh --lifecycles): "
    f"the {CI_DEPLOY} contexts of {FILE_META_LIFECYCLE}, comma/space-separated."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    context = load().context_of(
        on_github=ctx.on_gha,
        repository=eb.get("GITHUB_REPOSITORY"),
        ref=eb.get("GITHUB_REF"),
        event=eb.get("GITHUB_EVENT_NAME"),
    )
    eb.setdefault(KEY, default_envelope(context), comment=COMMENT)
