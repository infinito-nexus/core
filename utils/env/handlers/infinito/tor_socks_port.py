"""INFINITO_TOR_SOCKS_PORT: node Tor SOCKS port, read from the single source of
truth in svc-net-tor's meta/services.yml (services.tor.ports.local.socks). Keeps
shell consumers (e.g. the Playwright rerunner) off a hard-coded port literal.

Stdlib line parse on purpose: env handlers feed the .env generation, which
bootstraps fresh hosts before PyYAML exists (canonical pattern:
utils/storage/nfs.py)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TOR_SOCKS_PORT"
COMMENT = "Node Tor SOCKS port (SPOT: svc-net-tor services.tor.ports.local.socks)."

_LOCAL_RE = re.compile(r"^    local:\s*$")
_SOCKS_RE = re.compile(r"^      socks:\s*(\S+)\s*$")


def _read_socks_port(text: str) -> str | None:
    in_local = False
    for line in text.splitlines():
        if _LOCAL_RE.match(line):
            in_local = True
            continue
        if in_local:
            match = _SOCKS_RE.match(line)
            if match:
                return match.group(1)
            if line.strip() and not line.startswith("      "):
                in_local = False
    return None


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    services = ctx.repo_root / "roles" / "svc-net-tor" / ROLE_FILE_META_SERVICES
    try:
        text = read_text(str(services))
    except OSError:
        return
    port = _read_socks_port(text)
    if port is not None:
        eb.set(KEY, port, comment=COMMENT)
