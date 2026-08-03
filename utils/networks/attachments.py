"""Attachment computation for the compose networks renderers.

Which provider overlays a role attaches to, and which proxy aliases the
default network harvests, derived from the service_registry. Kept apart from
the emitters in :mod:`utils.networks.render` so a change to the consumer rules
cannot be confused with a change to the YAML they produce.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def _is_consumer(
    entry: dict[str, Any],
    application_id: str,
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
) -> bool:
    overlay = entry.get("overlay") or {}
    consumer = overlay.get("consumer") or {}
    kind = consumer.get("kind") or "services_flags"
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
    default_aliases: list[str] = []

    for entry in registry.values():
        if "canonical" in entry:
            continue
        overlay = entry.get("overlay")
        if not overlay:
            continue
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

    return attachments, default_aliases
