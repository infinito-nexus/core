"""INFINITO_TOR_SOCKS_PORT: node Tor SOCKS port, read from the single source of
truth in svc-net-tor's meta/services.yml (services.tor.ports.local.socks). Keeps
shell consumers (e.g. the Playwright rerunner) off a hard-coded port literal."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_TOR_SOCKS_PORT"
COMMENT = "Node Tor SOCKS port (SPOT: svc-net-tor services.tor.ports.local.socks)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    services = ctx.repo_root / "roles" / "svc-net-tor" / ROLE_FILE_META_SERVICES
    data = load_yaml_any(str(services), default_if_missing={})
    ports = (((data or {}).get("tor") or {}).get("ports") or {}).get("local") or {}
    port = ports.get("socks")
    if port is not None:
        eb.set(KEY, str(port), comment=COMMENT)
