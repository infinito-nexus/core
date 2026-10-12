from __future__ import annotations

import json
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_driver', probe, network_role_id) }}

    Args:
      probe: the registered result of
        `container network ls --filter name=<entity> --format '{{json .}}'`.
      network_role_id: the role whose entity name names the network.

    Returns:
      The driver of the network named exactly after that entity, '' when none exists.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('network_driver', probe, network_role_id) expects exactly 2 terms"
            )

        probe, network_role_id = terms
        name = get_entity_name(str(network_role_id))
        lines = probe.get("stdout_lines") if isinstance(probe, dict) else None
        for line in lines or []:
            try:
                network = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AnsibleError(
                    f"lookup('network_driver'): unparsable probe line {line!r}"
                ) from exc
            if network.get("Name") == name:
                return [str(network.get("Driver", ""))]
        return [""]
