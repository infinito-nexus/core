"""Lookup `mesh_address`: a host's primary mesh address, or '' off the mesh.

Usage:

    {{ lookup('mesh_address', STACK_HOST) }}

Takes exactly one term, the inventory hostname.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.mesh import primary_address


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if not terms or len(terms) != 1:
            raise AnsibleError("lookup('mesh_address', <hostname>) takes one term")
        host = str(terms[0]).strip()
        hostvars = (variables or {}).get("hostvars") or {}
        try:
            applications = hostvars[host].get("applications") or {}
        except KeyError:
            applications = {}
        return [primary_address(applications, host)]
