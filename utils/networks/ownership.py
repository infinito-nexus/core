"""Check that the docker networks on a host belong to the roles that own them:
named after the entity, labelled with it as compose project, holding a subnet
inside the declared block, and no network on a subnet another role declares.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

PROJECT_LABEL = "com.docker.compose.project"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _subnets(network: Mapping[str, Any]) -> list[Network]:
    configs = (network.get("IPAM") or {}).get("Config") or []
    return [
        ipaddress.ip_network(config["Subnet"], strict=False)
        for config in configs
        if config.get("Subnet")
    ]


def _within(subnets: list[Network], block: Network) -> bool:
    held = [entry for entry in subnets if entry.version == block.version]
    return bool(held) and all(entry.subnet_of(block) for entry in held)


def ownership_errors(
    networks: Iterable[Mapping[str, Any]],
    declared: Mapping[str, Iterable[tuple[str, str]]],
) -> list[str]:
    """Every way the host's networks contradict the roles that own them.

    Args:
        networks: ``docker network inspect`` objects of every network on the host.
        declared: entity name -> every (role id, declared subnet) of the roles
            the host deploys on that entity. Roles sharing an entity (a UI role
            beside its service) each pass with their own subnet; a network
            created before its role's block was widened passes while it stays
            inside the block.

    Returns:
        One message per contradiction; empty when every network belongs to
        its entity and no network occupies a subnet another role declares.
        A network named after its entity without any compose project label,
        or labelled with a declaring role id as older deploys did, passes on
        its subnet alone; a label naming another project fails.
    """
    owners = {
        entity: [
            (role, ipaddress.ip_network(subnet)) for role, subnet in sorted(claims)
        ]
        for entity, claims in sorted(declared.items())
    }
    errors: list[str] = []
    for network in networks:
        name = str(network.get("Name", ""))
        subnets = _subnets(network)
        project = (network.get("Labels") or {}).get(PROJECT_LABEL, "")
        if name in owners:
            claims = owners[name]
            if not any(_within(subnets, subnet) for _, subnet in claims):
                versions = {subnet.version for _, subnet in claims}
                listing = (
                    ", ".join(
                        str(entry) for entry in subnets if entry.version in versions
                    )
                    or "no subnet"
                )
                expected = " or ".join(
                    f"{role} declares {subnet}" for role, subnet in claims
                )
                errors.append(f"network '{name}' holds {listing}, but {expected}")
            if project and project not in {name} | {role for role, _ in claims}:
                errors.append(
                    f"network '{name}' belongs to compose project '{project}', "
                    f"but it is the network of {' or '.join(role for role, _ in claims)}"
                )
        for entity, claims in owners.items():
            if entity in (name, project):
                continue
            for role, subnet in claims:
                clash = [
                    str(entry)
                    for entry in subnets
                    if entry.version == subnet.version and entry.overlaps(subnet)
                ]
                if clash:
                    errors.append(
                        f"network '{name}' occupies {', '.join(clash)}, which {role} "
                        f"declares for its network '{entity}'"
                    )
    return errors
