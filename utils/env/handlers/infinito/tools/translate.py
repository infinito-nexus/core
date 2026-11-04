"""INFINITO_TOOLS_TRANSLATE_PORT: loopback port the tools runner forwards
to its translation gateway, read from roles/web-svc-translate/meta/services.yml."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TOOLS_TRANSLATE_PORT"
COMMENT = "Loopback port the tools runner forwards to its translation gateway."
SERVICES = f"roles/web-svc-translate/{ROLE_FILE_META_SERVICES}"
HTTP_PORT = re.compile(
    r"^translate:\n(?:.*\n)*?\s+local:\n\s+http:\s*(\d+)\s*$", re.MULTILINE
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    services = ctx.repo_root / SERVICES
    if not services.is_file():
        return
    found = HTTP_PORT.search(read_text(services))
    if found:
        eb.setdefault(KEY, found.group(1), comment=COMMENT)
