"""INFINITO_GIT_AUTHOR_NAME / INFINITO_GIT_AUTHOR_EMAIL: the identity this
checkout commits under. The test container mounts the checkout but not the
contributor's git configuration, so the suite cannot ask git who is about to
commit; the ``.env`` carries the answer across."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

NAME_KEY = "INFINITO_GIT_AUTHOR_NAME"
EMAIL_KEY = "INFINITO_GIT_AUTHOR_EMAIL"
NAME_COMMENT = "Name this checkout commits under; empty when git has none."
EMAIL_COMMENT = "Address this checkout commits under; empty when git has none."


def _configured(repo_root, key: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "config", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return result.stdout.strip()


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(NAME_KEY, _configured(ctx.repo_root, "user.name"), comment=NAME_COMMENT)
    eb.set(EMAIL_KEY, _configured(ctx.repo_root, "user.email"), comment=EMAIL_COMMENT)
