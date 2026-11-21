"""NIX_CONFIG: pass-through of the caller's access-tokens line on a GitHub runner.

`.env` is consumed by bash `source` and docker-compose `--env-file`, neither
of which round-trips multi-line values; the writer therefore rejects them.
Other NIX_CONFIG settings (`accept-flake-config`, `experimental-features`, …)
belong in `/etc/nix/nix.conf` (Dockerfile injects them inside the dev
container; host operators set them once in `~/.config/nix/nix.conf`).

Only a GitHub Actions runner gets the line: there the token is the job's
short-lived GITHUB_TOKEN. Under act or on a developer machine it is the
operator's own long-lived token, and `.env` would keep it in plaintext in the
host checkout.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

KEY = "NIX_CONFIG"
COMMENT = "The caller's NIX_CONFIG access-tokens line, on a GitHub runner only."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    if not ctx.on_gha:
        return
    nix_config = os.environ.get("NIX_CONFIG", "")
    access_tokens_line = next(
        (
            line.strip()
            for line in nix_config.splitlines()
            if line.lstrip().startswith("access-tokens")
        ),
        "",
    )
    if access_tokens_line:
        eb.set(KEY, access_tokens_line, comment=COMMENT)
