"""Attachment computation for the compose networks renderers.

Which provider overlays a role attaches to, and which proxy aliases the
default network harvests, derived from the service_registry. Kept apart from
the emitters in :mod:`utils.networks.render` so a change to the consumer rules
cannot be confused with a change to the YAML they produce.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.networks import STREAM_RELAY
from utils.networks.proxy import REVERSE_PROXY_APPLICATION_ID
from utils.roles.entity.name import entity_name

if TYPE_CHECKING:
    from collections.abc import Callable

UNPROVEN_STREAM_RELAY_MODES = frozenset({"swarm"})


def stream_relay_active(
    entry: dict[str, Any],
    deployment_mode: str,
    lookup_config: Callable[[str, str, Any], Any],
) -> bool:
    """Whether the reverse proxy relays the provider's streams in this mode.

    Args:
        entry: the provider's service_registry entry.
        deployment_mode: compose or swarm, after any per-role override.
        lookup_config: config value accessor.

    Returns:
        True when the provider's overlay declares ``stream_relay``, the
        reverse proxy's own overlay applies in ``deployment_mode`` (it runs on
        the host network everywhere else), and the provider's
        ``stream_relay.switch`` config path is true.

    Raises:
        ValueError: the provider declares ``stream_relay`` without a switch,
            or switches it on in one of ``UNPROVEN_STREAM_RELAY_MODES``. Every
            network lookup of the provider and the reverse proxy reaches this
            refusal, so no role of a deploy can render the relay before its
            live proof.
    """
    relay = (entry.get("overlay") or {}).get(STREAM_RELAY)
    if not relay:
        return False
    proxy_modes = lookup_config(
        REVERSE_PROXY_APPLICATION_ID, "networks.overlay.modes", []
    )
    if deployment_mode not in (proxy_modes or []):
        return False
    role = entry.get("role") or ""
    switch = str(relay.get("switch") or "").strip()
    if not switch:
        raise ValueError(f"{role}: overlay.{STREAM_RELAY} needs a switch")
    active = _coerce_bool(lookup_config(role, switch, False))
    if active and deployment_mode in UNPROVEN_STREAM_RELAY_MODES:
        raise ValueError(
            f"{role}: {switch} is true on a {deployment_mode} deploy, and the "
            "stream relay through the reverse proxy is not proven there: see "
            "the requirement 'OpenLDAP LDAPS through openresty in swarm' under "
            f"docs/requirements/. Set {switch} to false for this deploy."
        )
    return active


def _stream_relay_attachment(
    entry: dict[str, Any],
    application_id: str,
    deployment_mode: str,
    lookup_config: Callable[[str, str, Any], Any],
) -> dict[str, Any] | None:
    is_provider = application_id == entry.get("role")
    if not is_provider and application_id != REVERSE_PROXY_APPLICATION_ID:
        return None
    if not stream_relay_active(entry, deployment_mode, lookup_config):
        return None
    return {
        "role": entry["role"],
        "network": f"{entry['entity_name']}-relay",
        "topology": STREAM_RELAY,
        "aliases": [entry["entity_name"]] if is_provider else [],
        "is_provider": is_provider,
    }


def _is_consumer(
    entry: dict[str, Any],
    application_id: str,
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
) -> bool:
    overlay = entry.get("overlay") or {}
    consumer = overlay.get("consumer") or {}
    declared = consumer.get("kind") or "services_flags"
    kinds = declared if isinstance(declared, list) else [declared]
    return any(
        _matches_kind(
            str(kind), entry, consumer, application_id, lookup_config, lookup_database
        )
        for kind in kinds
    )


def _matches_kind(
    kind: str,
    entry: dict[str, Any],
    consumer: dict[str, Any],
    application_id: str,
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
) -> bool:
    if kind == "database":
        if not _coerce_bool(lookup_database(application_id, "enabled")):
            return False
        if not _coerce_bool(lookup_database(application_id, "shared")):
            return False
        return lookup_database(application_id, "id") == entry.get("role")
    if kind == "services_flags":
        key = consumer.get("key") or entry.get("provides") or entry.get("entity_name")
        flags = consumer.get("flags") or ["enabled", "shared"]
        for flag in flags:
            if not _coerce_bool(
                lookup_config(application_id, f"services.{key}.{flag}", False)
            ):
                return False
        return True
    if kind == "mcp_client":
        if not _coerce_bool(lookup_config(application_id, "mcp.enabled", False)):
            return False
        if not _coerce_bool(lookup_config(application_id, "mcp.shared", False)):
            return False
        direction = str(
            lookup_config(application_id, "mcp.direction", "") or ""
        ).strip()
        if direction not in ("client", "both"):
            return False
        consumer_key = entity_name(application_id)
        if (
            lookup_config(application_id, f"services.{consumer_key}.mcp_consumer", None)
            is not True
        ):
            return False
        refusal = lookup_config(
            entry.get("role") or "", f"services.{consumer_key}.mcp_consumer", True
        )
        return refusal is not False
    if kind == "web_facing":
        return application_id.startswith(("web-app-", "web-svc-"))
    return False


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _compute_attachments(
    registry: dict[str, dict[str, Any]],
    application_id: str,
    deployment_mode: str,
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    attachments: list[dict[str, Any]] = []
    relays: list[dict[str, Any]] = []
    default_aliases: list[str] = []

    for entry in registry.values():
        if "canonical" in entry:
            continue
        overlay = entry.get("overlay")
        if not overlay:
            continue
        relay = _stream_relay_attachment(
            entry, application_id, deployment_mode, lookup_config
        )
        if relay:
            relays.append(relay)
        if deployment_mode not in overlay.get("modes", []):
            continue

        is_provider = application_id == entry.get("role")
        topology = overlay.get("topology")

        if is_provider:
            if topology == "default_net":
                default_aliases.extend(overlay.get("aliases") or [])
                for peer in registry.values():
                    peer_overlay = peer.get("overlay")
                    if not peer_overlay:
                        continue
                    if not peer_overlay.get("proxy_resolvable"):
                        continue
                    if deployment_mode not in peer_overlay.get("modes", []):
                        continue
                    if "canonical" in peer:
                        continue
                    if peer.get("role") == entry.get("role"):
                        continue
                    default_aliases.extend(
                        peer_overlay.get("proxy_aliases")
                        or peer_overlay.get("aliases")
                        or []
                    )
            elif topology:
                aliases = list(
                    overlay.get("aliases", [entry.get("entity_name")])
                    or [entry.get("entity_name")]
                )
                if overlay.get("collect_proxy_resolvable"):
                    for peer in registry.values():
                        peer_overlay = peer.get("overlay")
                        if not peer_overlay:
                            continue
                        if not peer_overlay.get("proxy_resolvable"):
                            continue
                        if deployment_mode not in peer_overlay.get("modes", []):
                            continue
                        if "canonical" in peer:
                            continue
                        if peer.get("role") == entry.get("role"):
                            continue
                        aliases.extend(
                            peer_overlay.get("proxy_aliases")
                            or peer_overlay.get("aliases")
                            or []
                        )
                attachments.append(
                    {
                        "role": entry["role"],
                        "topology": topology,
                        "aliases": aliases,
                        "is_provider": True,
                    }
                )
            continue

        if not topology:
            continue
        if _is_consumer(entry, application_id, lookup_config, lookup_database):
            attachments.append(
                {
                    "role": entry["role"],
                    "topology": topology,
                    "aliases": [],
                    "is_provider": False,
                }
            )

    return attachments + relays, default_aliases


def _suppress_default(
    application_id: str, lookup_database: Callable[[str, str], Any]
) -> bool:
    if not application_id.startswith(("svc-db-", "svc-ai-")):
        return False
    return not bool(lookup_database(application_id, "local"))


def _drops_default(
    application_id: str,
    attachments: list[dict[str, Any]],
    lookup_database: Callable[[str, str], Any],
) -> bool:
    """
    Args:
        application_id: role the compose file belongs to.
        attachments: what :func:`_compute_attachments` returns for it.
        lookup_database: database value accessor.

    Returns:
        Whether its compose file leaves ``default`` out; never for a role that
        joins no other network, whose start would otherwise fail with ``network
        <project>_default not found`` on the ``<entity>`` bridge.
    """
    return bool(attachments) and _suppress_default(application_id, lookup_database)


def _own_shared_net_provider(
    attachments: list[dict[str, Any]],
    own_entity: str,
    entity_name: Callable[[str], str],
) -> bool:
    return any(
        att["is_provider"]
        and att["topology"] == "shared_net"
        and entity_name(att["role"]) == own_entity
        for att in attachments
    )


def _shared_network_key(
    attachments: list[dict[str, Any]],
    own_entity: str,
    entity_name: Callable[[str], str],
) -> str:
    if _own_shared_net_provider(attachments, own_entity, entity_name):
        return own_entity
    return "default"
