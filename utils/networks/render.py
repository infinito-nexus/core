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


from utils.networks.attachments import (
    _coerce_bool,
    _compute_attachments,
    _is_consumer,
)

__all__ = [
    "_coerce_bool",
    "_compute_attachments",
    "_is_consumer",
    "compute_external_network_roles",
    "render_compose_networks",
    "render_container_networks",
    "shared_network_compose_key",
]


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


def _shared_network_key(
    attachments: list[dict[str, Any]],
    own_entity: str,
    get_entity_name: Callable[[str], str],
) -> str:
    if _own_shared_net_provider(attachments, own_entity, get_entity_name):
        return own_entity
    return "default"


def shared_network_compose_key(
    *,
    application_id: str,
    deployment_mode: str,
    registry: dict[str, dict[str, Any]],
    get_entity_name: Callable[[str], str],
    lookup_config: Callable[[str, str, Any], Any],
    lookup_database: Callable[[str, str], Any],
    node_local: bool = False,
) -> str:
    """Key under which the pre-created ``<entity>`` network appears in the
    rendered compose file, which is what docker compose stores in the
    ``com.docker.compose.network`` label. An app that provides its own
    ``shared_net`` gets that network under its entity key and renders a separate
    unnamed ``default``; every other app renders ``default`` with the entity as
    its name. :func:`render_compose_networks` derives its own branch from this
    same call, so the label a caller stamps cannot drift from what is rendered.

    Args:
        application_id: role the network belongs to.
        deployment_mode: compose or swarm.
        registry: service registry built from the merged applications.
        get_entity_name: role id to entity name.
        lookup_config: config value accessor.
        lookup_database: database value accessor.
        node_local: render as compose regardless of deployment_mode.
    """
    if node_local:
        deployment_mode = "compose"
    attachments, _ = _compute_attachments(
        registry, application_id, deployment_mode, lookup_config, lookup_database
    )
    return _shared_network_key(
        attachments, get_entity_name(application_id), get_entity_name
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
    is_own_shared_net_provider = (
        _shared_network_key(attachments, own_entity, get_entity_name) == own_entity
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
