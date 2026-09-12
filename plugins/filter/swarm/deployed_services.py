"""Name the services a ``docker stack deploy`` run reported acting on."""

from __future__ import annotations

import re
from typing import Any

_LINE = re.compile(r"^(?:Creating|Updating) service (\S+)")


def swarm_deployed_services(deploy_result: Any) -> list[str]:
    """Return the service names from a registered stack-deploy result.

    Args:
        deploy_result: the registered shell result of the deploy.

    Returns:
        Service names in the order the deploy reported them.
    """
    lines = (deploy_result or {}).get("stdout_lines") or []
    names = []
    for line in lines:
        match = _LINE.match(str(line).strip())
        if match:
            names.append(match.group(1))
    return names


class FilterModule:
    def filters(self):
        return {"swarm_deployed_services": swarm_deployed_services}
