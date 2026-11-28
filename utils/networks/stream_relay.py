"""Streams the reverse proxy relays over a provider's dedicated relay network.

A provider declares ``overlay.stream_relay`` with a ``switch`` and the
``ports`` it opens. While the switch is true and the reverse proxy's own
overlay applies in the mode, the provider and the reverse proxy share
``<entity>-relay`` and nothing else does, so the relay never puts the proxy on
the provider's overlay with its consumers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.networks.attachments import STREAM_RELAY, _stream_relay_attachment
from utils.networks.proxy import REVERSE_PROXY_APPLICATION_ID

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _relays(
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    lookup_config: Callable[[str, str, Any], Any],
) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for entry in registry.values():
        if "canonical" in entry:
            continue
        attachment = _stream_relay_attachment(
            entry, application_id, deployment_mode, lookup_config
        )
        if attachment:
            yield entry, attachment


def stream_relay_networks(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    lookup_config: Callable[[str, str, Any], Any],
) -> list[dict[str, str]]:
    """Relay networks the compose file of ``application_id`` joins.

    Args:
        application_id: the rendering role, the reverse proxy or a provider.
        deployment_mode: compose or swarm, after any per-role override.
        registry: service registry built from the merged applications.
        lookup_config: config value accessor.

    Returns:
        One dict per relay network in registry order, empty when the role
        relays nothing in this mode: ``name`` (``<entity>-relay``), the
        provider's pinned ``stream_relay.subnet``, and ``stack``, the
        provider's entity, whose stack namespace the network carries.

    Raises:
        ValueError: a relayed provider pins no ``stream_relay.subnet``.
    """
    networks: list[dict[str, str]] = []
    for entry, attachment in _relays(
        application_id, deployment_mode, registry, lookup_config
    ):
        subnet = str(entry["overlay"][STREAM_RELAY].get("subnet") or "").strip()
        if not subnet:
            raise ValueError(f"{entry['role']}: overlay.{STREAM_RELAY} needs a subnet")
        networks.append(
            {
                "name": attachment["network"],
                "subnet": subnet,
                "stack": entry["entity_name"],
            }
        )
    return networks


def stream_relay_ports(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    lookup_config: Callable[[str, str, Any], Any],
) -> list[dict[str, str]]:
    """``container_ports`` terms for every stream ``application_id`` relays.

    Args:
        application_id: the role whose compose file publishes the ports.
        deployment_mode: compose or swarm, after any per-role override.
        registry: service registry built from the merged applications.
        lookup_config: config value accessor.

    Returns:
        One dict term per relayed protocol, in registry order: the provider's
        entity as ``service``, the protocol, the provider as
        ``application_id``, ``container: same`` and ``mode: host``. Empty for
        every role but the reverse proxy and when it relays nothing.

    Raises:
        ValueError: a relayed provider declares no ``stream_relay.ports``.
    """
    if application_id != REVERSE_PROXY_APPLICATION_ID:
        return []
    terms: list[dict[str, str]] = []
    for entry, _ in _relays(application_id, deployment_mode, registry, lookup_config):
        protocols = entry["overlay"][STREAM_RELAY].get("ports") or []
        if not protocols:
            raise ValueError(f"{entry['role']}: overlay.{STREAM_RELAY} needs ports")
        terms.extend(
            {
                "service": entry["entity_name"],
                "protocol": str(protocol),
                "application_id": entry["role"],
                "container": "same",
                "mode": "host",
            }
            for protocol in protocols
        )
    return terms
