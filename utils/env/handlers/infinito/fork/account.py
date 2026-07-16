"""INFINITO_FORK_ACCOUNT: GitHub account holding the operator's fork,
defaulting to the local OS username."""

from __future__ import annotations

import getpass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_FORK_ACCOUNT"
COMMENT = (
    "GitHub account holding the operator's fork; defaults to the local OS "
    "username. Composed into INFINITO_FORK_REPOSITORY_URL."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(KEY, getpass.getuser(), comment=COMMENT)
