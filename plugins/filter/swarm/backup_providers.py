"""Filter ``backup_providers``: hosts the remote-2-local pull reaches."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part for part in re.split(r"[\s,]+", value) if part]
    return [str(item) for item in value]


def backup_providers(
    configured, ha_hosts: Iterable[str] | None, hostvars: Mapping
) -> list:
    """Return configured providers plus every HA database host, de-duplicated.

    Args:
        configured: ``services.remote-2-local.backup_providers``; list or a
            whitespace/comma separated string.
        ha_hosts: inventory names from ``lookup('db_backup', 'hosts')``.
        hostvars: Ansible ``hostvars``.

    Returns:
        a list of addresses, configured first, each HA host as its
        ``ansible_host`` or its inventory name.
    """
    providers = _as_list(configured)
    for host in _as_list(ha_hosts):
        address = (hostvars.get(host) or {}).get("ansible_host") or host
        providers.append(str(address))
    return list(dict.fromkeys(providers))


class FilterModule:
    def filters(self):
        return {"backup_providers": backup_providers}
