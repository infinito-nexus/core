"""Lookup ``address_pool_overlaps``: the docker default address pools of a
host that overlap a range the deploy addresses itself.

    {{ lookup('address_pool_overlaps', daemon_json, group_names, reserved) }}

Args:
    daemon_json: the text of ``/etc/docker/daemon.json``; ``{}`` when the
        file is absent.
    group_names: every group of the host, after the swarm auto-placement.
    reserved: name -> CIDR of every further range no pool may overlap, such
        as ``NETWORK_MESH_POOL`` and ``NETWORK_TOR_VIRTUAL_CIDR``.

Returns:
    The messages of :func:`utils.preflight.pools.address_pool_errors` against
    ``reserved`` and the ``networks.local.subnet`` of every role the deploy
    may run on the host.
"""

from __future__ import annotations

import json
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.preflight.context import deploy_closure_context
from utils.preflight.pools import address_pool_errors
from utils.roles.entity.name import entity_name

_SUBNET_PATH = "networks.local.subnet"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 3:
            raise AnsibleError(
                "lookup('address_pool_overlaps', daemon_json, group_names, reserved) "
                "expects exactly 3 terms"
            )
        daemon_json, group_names, reserved = terms
        try:
            daemon_config = json.loads(str(daemon_json))
        except json.JSONDecodeError as exc:
            raise AnsibleError(
                f"address_pool_overlaps: daemon.json is not JSON: {exc}"
            ) from exc
        if not isinstance(daemon_config, dict) or not isinstance(reserved, dict):
            raise AnsibleError(
                "address_pool_overlaps: daemon.json and reserved must both be mappings"
            )
        try:
            context = deploy_closure_context(self, variables, group_names)
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"address_pool_overlaps: {exc}") from exc

        ranges = [
            (f"{name} reserves", str(cidr)) for name, cidr in sorted(reserved.items())
        ]
        for role in context.roles:
            subnet = str(context.config(role, _SUBNET_PATH, "") or "").strip()
            if subnet:
                ranges.append(
                    (f"{role} declares for its network '{entity_name(role)}'", subnet)
                )
        try:
            return [address_pool_errors(daemon_config, ranges)]
        except ValueError as exc:
            raise AnsibleError(f"address_pool_overlaps: {exc}") from exc
