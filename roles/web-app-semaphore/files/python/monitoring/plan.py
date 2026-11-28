from __future__ import annotations

import ipaddress
import re
import socket

from monitoring.survey import (
    ALIAS_PREFIX,
    SHARE,
    RefusalError,
    checked_address,
    checked_domain,
    matches,
)

SSH_USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
CHECKMK_KINDS = ("reachability", "agent")
PROMETHEUS_KINDS = ("health", "system", "traffic")
SHARE_KEY = "platform_monitoring"
HOST_KEY_VAR = SHARE.HOST_KEY_VARIABLE
SSH_USER_VAR = "ansible_user"
SSH_PORT_VAR = "ansible_port"
SSH_PORT = 22


def share_of(host, variables):
    """Args:
    host: the inventory host.
    variables: its host variables.

    Returns:
        Every share kind with its boolean, as the platform monitoring share
        schema reads it; a broken value raises :class:`RefusalError`.
    """
    try:
        return SHARE.share(variables.get(SHARE_KEY))
    except ValueError as error:
        raise RefusalError(f"{host}: {error}") from error


def _canonical(application):
    if not isinstance(application, dict):
        return []
    canonical = ((application.get("server") or {}).get("domains") or {}).get(
        "canonical"
    )
    values = canonical.values() if isinstance(canonical, dict) else canonical
    return list(values or [])


def canonical_domains(host, variables):
    """Args:
    host: the inventory host.
    variables: its host variables.

    Returns:
        ``DOMAIN_PRIMARY`` and every canonical domain the inventory names for
        an application of the host, sorted and unique, each checked as a
        lowercase domain.
    """
    found = set()
    if "DOMAIN_PRIMARY" in variables:
        found.add(
            checked_domain(variables["DOMAIN_PRIMARY"], f"DOMAIN_PRIMARY of {host}")
        )
    for application, value in (variables.get("applications") or {}).items():
        for domain in _canonical(value):
            found.add(
                checked_domain(domain, f"a canonical domain of {application} on {host}")
            )
    return sorted(found)


def federation_domain(host, variables):
    """Args:
    host: the inventory host.
    variables: its host variables.

    Returns:
        ``federation_domain`` of ``utils/platform_monitoring.py``; refuses
        where it raises.
    """
    try:
        return SHARE.federation_domain(variables)
    except ValueError as error:
        raise RefusalError(f"{host} {error}") from error


def ssh_access(host, variables):
    """Args:
    host: the inventory host.
    variables: its host variables.

    Returns:
        ``user``, ``port``, ``key_type`` and ``key`` Checkmk pulls the agent
        with: the login user, its port and the pinned host key of the
        inventory; refuses a missing or malformed one.
    """
    user = variables.get(SSH_USER_VAR)
    if not matches(SSH_USER, user):
        raise RefusalError(f"{SSH_USER_VAR} of {host} is no login name")
    # Exception: Ansible logs in on 22 without ansible_port, and Checkmk must pull where Ansible logs in, so the absent variable falls back to 22.
    port = variables.get(SSH_PORT_VAR, SSH_PORT)
    if isinstance(port, str) and port.isdigit():
        port = int(port)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        raise RefusalError(f"{SSH_PORT_VAR} of {host} is no TCP port")
    line = variables.get(HOST_KEY_VAR)
    if SHARE.host_key_refusals(line, HOST_KEY_VAR):
        raise RefusalError(f"{HOST_KEY_VAR} of {host} is no OpenSSH host key line")
    key_type, key = line.split(" ")
    return {"user": user, "port": str(port), "key_type": key_type, "key": key}


def resolve(name):
    """Args:
    name: a hostname or domain the store wrote.

    Returns:
        Every A and AAAA address the resolver answers for it, empty when it
        answers none.
    """
    try:
        answers = socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    return sorted({answer[4][0] for answer in answers})


def external(value, what, private, resolver):
    """Args:
    value: a checked ``ansible_host`` or domain the store wrote.
    what: its place, as the refusal names it.
    private: the networks WORKSPACE_PRIVATE_TARGETS opens, the test
        variant's own.
    resolver: :func:`resolve` or a stand-in.

    Returns:
        The addresses checked: ``value`` itself for an IP literal, else every
        address it resolves to. It refuses when one of them is an
        ``internal_address`` of ``utils/platform_monitoring.py`` outside
        ``private``, so no platform check aims inward, and when a name
        resolves to nothing unless ``private`` opens a network.
    """
    try:
        addresses = [str(ipaddress.ip_address(value))]
    except ValueError:
        if SHARE.internal_address(value):
            raise RefusalError(f"{what} {value} is an internal address") from None
        addresses = resolver(value)
        if not addresses and not private:
            raise RefusalError(f"{what} {value} resolves to no address") from None
    for address in addresses:
        if SHARE.internal_address(address):
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
            if not any(parsed in network for network in private):
                raise RefusalError(
                    f"{what} {value} is an internal address"
                    + ("" if address == value else f" ({address})")
                )
    return addresses


def pinned(value, addresses):
    """Args:
    value: the checked ``ansible_host``.
    addresses: what :func:`external` checked for it.

    Returns:
        The address Checkmk monitors: the first checked IPv4 address, else
        the first checked one, so Checkmk never resolves the name again and a
        rebinding cannot aim its checks inward; ``value`` itself only when
        nothing resolved, which only a test variant's private network admits.
    """
    if not addresses:
        return value
    return next((a for a in addresses if ":" not in a), addresses[0])


def workspace_domains(primary, domains):
    """Args:
    primary: the host's ``deploy_domain``, ``<label>.ws-<id>.<zone>``.
    domains: the checked domains of the host.

    Returns:
        The ``domains`` under ``ws-<id>.<zone>``, the names the platform
        places, so no HTTPS check probes a third party's site.
    """
    suffix = primary.split(".", 1)[1]
    return [d for d in domains if d == suffix or d.endswith(f".{suffix}")]


def refuse_worker_federation(host, inventory):
    """Args:
    host: MONITOR_HOST, which shares ``health``, ``system`` or ``traffic``.
    inventory: ``ansible-inventory --list`` of the task's pinned commit.

    Raises:
        RefusalError: the host is a worker, or the stack order is
            ambiguous. The stack's digest file lives on its stack host,
            which a workspace task of the worker never reaches, so only the
            stack host federates and its release takes every digest line.
    """
    try:
        stack = SHARE.stack_host(inventory, host)
    except ValueError as error:
        raise RefusalError(f"{host}: {error}") from error
    if stack != host:
        raise RefusalError(
            f"{host} is a worker of {stack}: share health, system and traffic"
            f" on {stack}, whose /federate serves the stack"
        )


def plan(workspace, action, host, inventory, private, primary, resolver):
    """Args:
    workspace: the bare workspace id.
    action: ``apply`` or ``remove``.
    host: MONITOR_HOST.
    inventory: ``ansible-inventory --list`` of the task's pinned commit.
    private: the networks WORKSPACE_PRIVATE_TARGETS opens.
    primary: the host's ``deploy_domain`` of ``lib.sh``, the DOMAIN_PRIMARY
        its deploy passes; it replaces the inventory's, which the store
        writes. Empty for ``remove``.
    resolver: :func:`resolve` or a stand-in.

    Returns:
        ``workspace``, its ``alias`` ``ws-<id>`` that names it in Checkmk,
        Prometheus and OpenBao, ``action``, ``host``, the ``label`` of
        ``primary`` and its ``entry``: the ``share``, ``address``
        (:func:`pinned`),
        ``domains`` (:func:`workspace_domains`), ``federation`` domain,
        ``ssh`` access and whether it belongs in Checkmk and in Prometheus;
        ``remove`` plans no entry. An internal address or domain refuses
        (:func:`external`).
    """
    entry = None
    label = None
    if action == "apply":
        hostvars = (inventory.get("_meta") or {}).get("hostvars") or {}
        if host not in hostvars:
            raise RefusalError(f"{host} is no host of the pinned inventory")
        variables = {
            **(hostvars[host] or {}),
            "DOMAIN_PRIMARY": checked_domain(primary, f"the deploy domain of {host}"),
        }
        label = primary.split(".", 1)[0]
        share = share_of(host, variables)
        prometheus = any(share[kind] for kind in PROMETHEUS_KINDS)
        if prometheus:
            refuse_worker_federation(host, inventory)
        if "ansible_host" not in variables:
            raise RefusalError(f"{host} names no ansible_host")
        what = f"ansible_host of {host}"
        domains = workspace_domains(primary, canonical_domains(host, variables))
        federation = federation_domain(host, variables) if prometheus else None
        for domain in (*domains, *([federation] if federation else [])):
            external(domain, f"a domain of {host}", private, resolver)
        address = checked_address(variables["ansible_host"], what)
        entry = {
            "share": share,
            "address": pinned(address, external(address, what, private, resolver)),
            "domains": domains,
            "federation": federation,
            "ssh": ssh_access(host, variables) if share["agent"] else None,
            "checkmk": any(share[kind] for kind in CHECKMK_KINDS),
            "prometheus": prometheus,
        }
    return {
        "workspace": workspace,
        "alias": f"{ALIAS_PREFIX}{workspace}",
        "action": action,
        "host": host,
        "label": label,
        "entry": entry,
    }
