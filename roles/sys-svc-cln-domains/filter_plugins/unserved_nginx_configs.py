from __future__ import annotations

import re
from pathlib import PurePosixPath

_DOMAIN = re.compile(r"^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+$")


def unserved_nginx_configs(paths: list[str], served: list[str]) -> list[str]:
    """Pick the per-domain nginx configs of domains the host no longer serves.

    Args:
        paths: nginx config files, named ``<domain>.conf``.
        served: every domain the host serves, CURRENT_PLAY_DOMAINS_ALL.

    Returns:
        The sorted paths whose ``<domain>`` is a domain the host does not
        serve; files not named after a domain and onion services are kept.
    """
    keep = {str(domain).strip().lower() for domain in served}
    unserved = []
    for path in paths:
        name = PurePosixPath(path).name
        if not name.endswith(".conf"):
            continue
        domain = name[: -len(".conf")].lower()
        if not _DOMAIN.match(domain) or domain.endswith(".onion"):
            continue
        if domain not in keep:
            unserved.append(path)
    return sorted(unserved)


class FilterModule:
    def filters(self):
        return {"unserved_nginx_configs": unserved_nginx_configs}
