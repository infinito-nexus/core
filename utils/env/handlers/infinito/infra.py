from __future__ import annotations

from typing import TYPE_CHECKING

from utils.networks.infra import SUBNET_KEY, runner_ip

if TYPE_CHECKING:
    from utils.env.context import BuildContext, EnvBuilder

RUNNER_CONTAINER_KEY = "INFINITO_INFRA_RUNNER_CONTAINER"
RUNNER_IP_KEY = "INFINITO_INFRA_RUNNER_IP"
RUNNER_CONTAINER = "infinito-infra-runner"
RUNNER_IP_COMMENT = (
    "Fixed address of the infra runner: host .2 of INFINITO_INFRA_SUBNET."
)
CACHE_IP_KEYS = (
    "INFINITO_CACHE_REGISTRY_IP",
    "INFINITO_CACHE_PACKAGE_IP",
    "INFINITO_CACHE_PACKAGE_FRONTEND_IP",
)
CACHE_IP_COMMENT = "The infra runner serves this cache; every consumer reaches it at the runner address."
RUNNER_CONTAINER_COMMENT = "Container name of the machine-wide infra runner that hosts the caches and the tools."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    subnet = eb.get(SUBNET_KEY)
    if not subnet:
        return
    address = runner_ip(subnet)
    eb.set(RUNNER_IP_KEY, address, comment=RUNNER_IP_COMMENT)
    for key in CACHE_IP_KEYS:
        eb.set(key, address, comment=CACHE_IP_COMMENT)
    eb.setdefault(
        RUNNER_CONTAINER_KEY, RUNNER_CONTAINER, comment=RUNNER_CONTAINER_COMMENT
    )
