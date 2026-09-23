"""INFINITO_I18N_LIBRETRANSLATE_PORT: loopback port the i18n runner forwards to
its LibreTranslate, read from roles/web-svc-libretranslate/meta/services.yml."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_I18N_LIBRETRANSLATE_PORT"
COMMENT = "Loopback port the i18n runner forwards to its LibreTranslate."
SERVICES = f"roles/web-svc-libretranslate/{ROLE_FILE_META_SERVICES}"
HTTP_PORT = re.compile(r"^\s+local:\n\s+http:\s*(\d+)\s*$", re.MULTILINE)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    services = ctx.repo_root / SERVICES
    if not services.is_file():
        return
    found = HTTP_PORT.search(read_text(services))
    if found:
        eb.setdefault(KEY, found.group(1), comment=COMMENT)
