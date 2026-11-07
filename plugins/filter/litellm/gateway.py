"""Which gateway URL a consumer may use, and which keys the gateway registers.

A consumer reaches the gateway in one of three ways. Beside the gateway on the
container network it names the gateway's service on its internal port; on the
host itself it names a loopback address on the published port; on a host that
runs no gateway of its own it names the gateway host's mesh address on the
published port. Each mode admits exactly one shape, so a consumer that would
send its prompts and its key anywhere else fails the deploy instead.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit

from ansible.errors import AnsibleFilterError

HOST_ALIAS_PREFIX = "host:"
CONTAINER = "container"
LOOPBACK = "loopback"
MESH = "mesh"
MODES = (CONTAINER, LOOPBACK, MESH)


def _port_of(parts) -> int | None:
    try:
        return parts.port
    except ValueError:
        return None


def _container_refusal(hostname: str, own_domain: str) -> str:
    if "." in hostname:
        return (
            f"'{hostname}' is dotted, and the dns-search suffix turns a dotted "
            "host into the public FQDN routed through the ingress"
        )
    if own_domain and hostname == own_domain:
        return f"'{hostname}' is the consumer's own domain"
    return ""


def _mesh_refusal(hostname: str, mesh_address: str) -> str:
    if not mesh_address:
        return (
            "this host's mesh interfaces list no peer address for the gateway "
            "host, so it cannot reach the gateway over the mesh"
        )
    try:
        ipaddress.IPv4Address(hostname)
    except ValueError:
        return f"'{hostname}' is not an IPv4 mesh address"
    if hostname != mesh_address:
        return f"'{hostname}' is not the gateway host's mesh address '{mesh_address}'"
    return ""


def litellm_gateway_refusal(
    url,
    mode,
    port,
    loopback_hosts: Iterable[str] = (),
    own_domain: str = "",
    mesh_address: str = "",
) -> str:
    """Why ``url`` is refused as a consumer's gateway base URL, or ``''``.

    Args:
        url: the base URL the consumer would send inference traffic to.
        mode: ``container`` for a consumer on the gateway's container
            network, ``loopback`` for one that runs on the gateway's host,
            ``mesh`` for every consumer of a host that uses the gateway of
            another host.
        port: the one port the URL may name: the internal port in
            ``container`` mode, the published port otherwise.
        loopback_hosts: the hosts ``loopback`` mode accepts.
        own_domain: the consumer's own domain, which ``container`` mode
            refuses.
        mesh_address: the gateway host's address as this host's own mesh
            interface lists it; ``mesh`` mode accepts no other host.
    """
    if mode not in MODES:
        raise AnsibleFilterError(
            f"litellm_gateway_refusal: mode '{mode}' is not one of {', '.join(MODES)}"
        )
    parts = urlsplit(str(url or ""))
    if parts.scheme != "http":
        return f"scheme '{parts.scheme}' is not plain http"
    hostname = parts.hostname or ""
    if not hostname:
        return "the URL names no host"
    if _port_of(parts) != int(port):
        return f"port '{_port_of(parts)}' is not the gateway port {int(port)}"
    if mode == CONTAINER:
        return _container_refusal(hostname, own_domain)
    if mode == LOOPBACK:
        allowed = [str(host) for host in loopback_hosts]
        if hostname not in allowed:
            return f"'{hostname}' is not one of {', '.join(allowed)}"
        return ""
    return _mesh_refusal(hostname, str(mesh_address or ""))


def litellm_gateway_keys(local_keys, host_keys) -> list[dict[str, str]]:
    """Every virtual key the gateway registers, local consumers first.

    Args:
        local_keys: ``[{alias, key}]`` of the consumers deployed beside the
            gateway, each aliased by its application id.
        host_keys: consuming host name to the key the inventory pass minted
            for it; each becomes ``host:<name>``, which no application id can
            collide with.

    Raises:
        AnsibleFilterError: a host key is empty, or two entries share an
            alias or a key. A shared key would make revoking one consumer
            revoke the other; the message names aliases only.
    """
    entries = [
        {"alias": str(entry["alias"]), "key": str(entry["key"])}
        for entry in local_keys or []
    ]
    if not isinstance(host_keys or {}, Mapping):
        raise AnsibleFilterError("litellm_gateway_keys: host_keys must be a mapping")
    for host, key in sorted((host_keys or {}).items()):
        if not str(key or "").strip():
            raise AnsibleFilterError(
                f"litellm_gateway_keys: consuming host '{host}' carries an empty "
                "key; re-run cli.administration.inventory.gateway"
            )
        entries.append({"alias": HOST_ALIAS_PREFIX + str(host), "key": str(key)})
    aliases = [entry["alias"] for entry in entries]
    repeated = sorted({alias for alias in aliases if aliases.count(alias) > 1})
    if repeated:
        raise AnsibleFilterError(
            f"litellm_gateway_keys: alias(es) registered twice: {', '.join(repeated)}"
        )
    holders: dict[str, list[str]] = {}
    for entry in entries:
        holders.setdefault(entry["key"], []).append(entry["alias"])
    shared = sorted(" and ".join(names) for names in holders.values() if len(names) > 1)
    if shared:
        raise AnsibleFilterError(
            f"litellm_gateway_keys: one key is held by {'; '.join(shared)}"
        )
    return entries


class FilterModule:
    """Expose the gateway URL contract and key list to the gateway tasks."""

    def filters(self):
        return {
            "litellm_gateway_refusal": litellm_gateway_refusal,
            "litellm_gateway_keys": litellm_gateway_keys,
        }
