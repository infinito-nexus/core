"""NIX_CONFIG: pass-through of the caller's access-tokens line, when present.

`.env` is consumed by bash `source` and docker-compose `--env-file`, neither
of which round-trips multi-line values; the writer therefore rejects them.
Other NIX_CONFIG settings (`accept-flake-config`, `experimental-features`, …)
belong in `/etc/nix/nix.conf` (Dockerfile injects them inside the dev
container; host operators set them once in `~/.config/nix/nix.conf`).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "NIX_CONFIG"
COMMENT = "Pass-through of the caller's NIX_CONFIG access-tokens line, when present."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
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
