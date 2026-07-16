"""INFINITO_FORK_REPOSITORY_URL: GitHub URL of the operator's fork, composed
from INFINITO_FORK_ACCOUNT and INFINITO_FORK_REPOSITORY_NAME."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_FORK_REPOSITORY_URL"
COMMENT = (
    "GitHub URL of the operator's fork, composed from INFINITO_FORK_ACCOUNT "
    "and INFINITO_FORK_REPOSITORY_NAME."
)


def compose(account: str, name: str) -> str:
    return f"https://github.com/{account}/{name}"


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(
        KEY,
        compose(
            eb.get("INFINITO_FORK_ACCOUNT"),
            eb.get("INFINITO_FORK_REPOSITORY_NAME"),
        ),
        comment=COMMENT,
    )
