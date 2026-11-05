"""INFINITO_TOOLS_S1_PORT: loopback port the tools runner forwards
to its System One, read from roles/svc-ai-s1/meta/services.yml."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TOOLS_S1_PORT"
COMMENT = "Loopback port the tools runner forwards to its System One."
SERVICES = f"roles/svc-ai-s1/{ROLE_FILE_META_SERVICES}"
HTTP_PORT = re.compile(r"^s1:\n(?:.*\n)*?\s+local:\n\s+http:\s*(\d+)\s*$", re.MULTILINE)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    services = ctx.repo_root / SERVICES
    if not services.is_file():
        return
    found = HTTP_PORT.search(read_text(services))
    if found:
        eb.setdefault(KEY, found.group(1), comment=COMMENT)
