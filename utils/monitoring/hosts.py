"""Host names of the platform monitoring share: their one canonical form,
the path segment derived from it and the stack host of a swarm."""

from __future__ import annotations

import ipaddress
import re
import socket

HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
CANONICAL_HOSTNAME = re.compile(rf"(?=.{{1,253}}$){HOST_LABEL}(?:\.{HOST_LABEL})*")
DOMAIN = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
)
SWARM_MANAGERS = "svc-swarm-manager"


def canonical_host(value):
    """Args:
        value: a MONITOR_HOST or release HOST.

    Returns:
        The one form ``monitoring apply``, ``release`` and the deploy key a
        host by: the text ``ipaddress`` gives an IP literal, so
        ``2001:DB8::1`` and ``2001:db8:0::1`` name ``2001:db8::1``, or the
        name in lowercase.

    Raises:
        ValueError: ``value`` is no text, carries an IPv6 scope id, is a
            name a legacy IPv4 reader takes for an address (``01.2.3.4``,
            ``127.1``, ``0x7f000001``), whose meaning depends on the reader,
            or is no hostname in any case.
    """
    spelled = _spelled(value if isinstance(value, str) else "")
    try:
        ipaddress.ip_address(spelled)
    except ValueError:
        if spelled.rsplit(".", 1)[-1].isdigit() or _legacy(spelled):
            raise ValueError(f"{value!r} is an ambiguous legacy IPv4 form") from None
        if not CANONICAL_HOSTNAME.fullmatch(spelled):
            raise ValueError(f"{value!r} is no host address or name") from None
    return spelled


def _spelled(value):
    if "%" in value:
        raise ValueError(f"{value} carries an IPv6 scope id")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return value.lower()


def _legacy(value):
    try:
        socket.inet_aton(value)
    except OSError:
        return False
    return True


def host_segment(host):
    """Args:
        host: an inventory host name, a hostname or an IP literal as the
            ``monitoring`` template checks it.

    Returns:
        ``canonical_host`` of ``host`` with every ``:`` as ``_``. Only an
        IPv6 literal holds a ``:`` and ``canonical_host`` refuses every name
        with a ``_``, so no two hosts share a segment: ``2001:db8::1`` gives
        ``2001_db8__1``, a name no other host can have. Checkmk host names,
        OpenBao paths, scrape file names and digest lines all use it.

    Raises:
        ValueError: ``canonical_host`` refuses ``host``.
    """
    return canonical_host(host).replace(":", "_")


def checkmk_host_name(workspace, host):
    """Args:
        workspace: ``ws-<id>``.
        host: the inventory host.

    Returns:
        The Checkmk host name, unique across workspaces and hosts:
        ``host_segment`` of ``host``. The ``monitoring`` template creates the
        host under it.
    """
    return f"{workspace}-{host_segment(host)}"


def stack_host(inventory, host):
    """Args:
        inventory: ``ansible-inventory --list`` of the workspace.
        host: the target host.

    Returns:
        ``STACK_HOST`` of ``group_vars/all/18_swarm.yml`` for ``host``: the
        first of ``groups['svc-swarm-manager']``, which Ansible orders as the
        group's own hosts, then its children's in listed order, then deeper
        descendants; the host itself only when the group holds none. The
        deploy writes the federation digest there.

    Raises:
        ValueError: the first manager sits below two or more groups of one
            level, where Ansible's order comes from a set.
    """
    seen, level, depth = {SWARM_MANAGERS}, [SWARM_MANAGERS], 0
    while level:
        found = [group for group in level if (inventory.get(group) or {}).get("hosts")]
        if found:
            if depth >= 2 and len(found) > 1:
                raise ValueError(
                    f"the first host of {SWARM_MANAGERS} is ambiguous: {found}"
                )
            return inventory[found[0]]["hosts"][0]
        children = []
        for group in level:
            for child in (inventory.get(group) or {}).get("children") or []:
                if child not in seen:
                    seen.add(child)
                    children.append(child)
        level, depth = children, depth + 1
    return host
