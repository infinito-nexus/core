"""Pure-Python rendering of compose networks blocks fed by the service_registry.

Two callable surfaces, mirroring what `roles/sys-svc-compose/templates/networks.yml.j2`
and `roles/sys-svc-container/templates/networks.yml.j2` used to emit:

* :func:`render_compose_networks` -> top-level ``networks:`` block (column 0)
* :func:`render_container_networks` -> per-service ``networks:`` attachment (4-space indent)

The schema lives at ``meta/networks.yml.overlay`` per provider role,
discovered into the service_registry by ``discover_role_services``. Keys:

* ``modes``: list of DEPLOYMENT_MODE values where this overlay applies
* ``topology``: ``shared_net`` | ``default_net``. Absent = beacon-only (no attachment)
* ``aliases``: list of DNS aliases. Default: ``[entity_name]`` for shared_net, ``[]`` for default_net
* ``consumer``: optional override
   * ``kind``: ``services_flags`` (default) | ``database``
   * ``key``: services.<key>.* lookup base. Default: provides or entity_name
   * ``flags``: list of flags to AND. Default: ``[enabled, shared]``
* ``proxy_resolvable``: beacon flag - the harvested aliases get attached to
   every ``default_net`` provider and every ``collect_proxy_resolvable``
   provider in the same mode.
* ``proxy_aliases``: aliases the beacon exposes for harvesting; falls back
   to ``aliases``. Set it when the overlay also has a topology whose own
   ``aliases`` (e.g. the entity name) must NOT land on the proxy.
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


def _suppress_default(application_id: str) -> bool:
    return application_id.startswith(("svc-db-", "svc-ai-"))


def _own_shared_net_provider(
    attachments: list[dict[str, Any]],
    own_entity: str,
    get_entity_name: Callable[[str], str],
) -> bool:
    return any(
        att["is_provider"]
        and att["topology"] == "shared_net"
        and get_entity_name(att["role"]) == own_entity
        for att in attachments
    )


def compute_external_network_roles(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
) -> list[str]:
    """Provider role names whose overlay ``render_compose_networks`` emits as
    ``external: true`` for ``application_id``. Mirrors the attachment filter in
    :func:`render_compose_networks` (every attachment except a ``default_net``
    the app provides itself). Used to pre-create those swarm overlays before
    ``docker stack deploy``: a consumer can reference a shared provider's
    network without that provider role having run in the same play, so the
    overlay would otherwise be missing at deploy time.
    """
    attachments, _ = _compute_attachments(
        registry, application_id, deployment_mode, lookup_config, lookup_database
    )
    roles: list[str] = []
    for att in attachments:
        if att["is_provider"] and att["topology"] == "default_net":
            continue
        role = att["role"]
        if role not in roles:
            roles.append(role)
    return roles


def render_compose_networks(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    get_entity_name: Callable[[str], str],
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
    swarm_encrypted: bool = True,
    node_local: bool = False,
) -> str:
    if node_local:
        deployment_mode = "compose"
    attachments, _ = _compute_attachments(
        registry, application_id, deployment_mode, lookup_config, lookup_database
    )
    lines: list[str] = ["networks:"]
    for att in attachments:
        if att["is_provider"] and att["topology"] == "default_net":
            continue
        lines.append(f"  {get_entity_name(att['role'])}:")
        lines.append("    external: true")

    own_entity = get_entity_name(application_id)
    is_own_shared_net_provider = _own_shared_net_provider(
        attachments, own_entity, get_entity_name
    )
    if not _suppress_default(application_id):
        lines.append("  default:")
        if deployment_mode == "swarm":
            if not is_own_shared_net_provider and own_entity:
                lines.append(f"    name: {own_entity}")
            lines.append("    driver: overlay")
            lines.append("    attachable: true")
            lines.append("    driver_opts:")
            lines.append(f'      encrypted: "{"true" if swarm_encrypted else "false"}"')
            if not is_own_shared_net_provider:
                subnet = lookup_config(application_id, "networks.local.subnet", "")
                if subnet:
                    lines.append("    ipam:")
                    lines.append("      driver: default")
                    lines.append("      config:")
                    lines.append(f"        - subnet: {subnet}")
        elif is_own_shared_net_provider:
            lines.append("    driver: bridge")
        else:
            subnet = lookup_config(application_id, "networks.local.subnet", "")
            if subnet:
                if own_entity:
                    lines.append(f"    name: {own_entity}")
                lines.append("    driver: bridge")
                lines.append("    ipam:")
                lines.append("      driver: default")
                lines.append("      config:")
                lines.append(f"        - subnet: {subnet}")

    return "\n".join(lines) + "\n"


def render_container_networks(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    get_entity_name: Callable[[str], str],
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
    provider_self_alias: bool = True,
    node_local: bool = False,
) -> str:
    if node_local:
        deployment_mode = "compose"
    attachments, default_aliases = _compute_attachments(
        registry, application_id, deployment_mode, lookup_config, lookup_database
    )
    lines: list[str] = ["networks:"]
    for att in attachments:
        if att["is_provider"] and att["topology"] == "default_net":
            continue
        lines.append(f"  {get_entity_name(att['role'])}:")
        aliases = att["aliases"]
        if att["is_provider"] and not provider_self_alias:
            aliases = []
        if aliases:
            lines.append("    aliases:")
            lines.extend(f"      - {alias}" for alias in aliases)
        else:
            lines.append("    {}")

    if not _suppress_default(application_id):
        if default_aliases:
            lines.append("  default:")
            lines.append("    aliases:")
            lines.extend(f"      - {alias}" for alias in default_aliases)
        else:
            lines.append("  default:")

    return "\n" + "\n".join(lines)
