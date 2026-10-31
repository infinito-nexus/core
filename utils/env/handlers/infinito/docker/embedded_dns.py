"""INFINITO_DOCKER_EMBEDDED_DNS_IP: the runtime's own resolver, read from the
networks SPOT (group_vars/all/08_networks.yml
NETWORK_DOCKER_EMBEDDED_DNS_RESOLVER)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.paths import read_group_value

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

NETWORKS = str(PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml")
KEY = "INFINITO_DOCKER_EMBEDDED_DNS_IP"
COMMENT = (
    "Resolver the container runtime answers compose aliases on "
    "(SPOT: group_vars/all/08_networks.yml NETWORK_DOCKER_EMBEDDED_DNS_RESOLVER)."
)


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.setdefault(
        KEY,
        read_group_value(NETWORKS, "NETWORK_DOCKER_EMBEDDED_DNS_RESOLVER"),
        comment=COMMENT,
    )
