"""Lookup `tor_egress_clients`: the address space Tor's egress ports admit.

Deliberately not the three RFC1918 blocks: 10.0.0.0/8 would hand the operator's
whole LAN a resolver and a transparent proxy that carry no access policy of
their own. What is admitted is what this deployment declares for itself, in rule
order: loopback, docker's address pools, the swarm gateway bridge, the role
subnet pool, and the subnets of the roles that sit outside it.

Usage:

    {{ lookup('tor_egress_clients') }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import trust_as_template

_REQUIRED = (
    "NETWORK_LOOPBACK_CIDR",
    "NETWORK_DOCKER_ADDRESS_POOLS",
    "NETWORK_SWARM_GWBRIDGE_POOL",
    "NETWORK_ROLE_SUBNET_POOL",
    "NETWORK_ROLE_SUBNET_EXCEPTION_ROLES",
)


def _rendered(templar: Any, value: Any) -> str:
    """A variable's value with its Jinja resolved.

    Group vars reach a lookup as whatever the file holds, and several of these
    are references rather than literals. Passing one through unrendered would
    put the template text itself into a source address, where it cannot match
    and therefore silently narrows the admitted set.
    """
    text = "" if value is None else str(value).strip()
    if "{{" not in text or templar is None:
        return text
    rendered = str(templar.template(trust_as_template(text))).strip()
    if "{{" in rendered:
        raise AnsibleError(f"tor_egress_clients: {text!r} did not render to an address")
    return rendered


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if terms:
            raise AnsibleError("lookup('tor_egress_clients') expects no terms.")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        missing = [name for name in _REQUIRED if variables.get(name) is None]
        if missing:
            raise AnsibleError(
                "tor_egress_clients: missing variable(s) "
                f"{', '.join(missing)}; an incomplete list would install a guard "
                "that admits more than it was asked to"
            )

        templar = getattr(self, "_templar", None)
        excepted = lookup_loader.get(
            "role_subnets",
            loader=getattr(self, "_loader", None),
            templar=templar,
        ).run(
            [variables["NETWORK_ROLE_SUBNET_EXCEPTION_ROLES"]],
            variables=variables,
        )[0]

        pools = variables["NETWORK_DOCKER_ADDRESS_POOLS"]
        if not isinstance(pools, (list, tuple)):
            raise AnsibleError(
                "tor_egress_clients: NETWORK_DOCKER_ADDRESS_POOLS must be a list"
            )
        bases = []
        for pool in pools:
            base = pool.get("base") if isinstance(pool, dict) else None
            if not base:
                raise AnsibleError(
                    f"tor_egress_clients: address pool {pool!r} declares no base"
                )
            bases.append(_rendered(templar, base))

        ordered = [
            _rendered(templar, variables["NETWORK_LOOPBACK_CIDR"]),
            *bases,
            _rendered(templar, variables["NETWORK_SWARM_GWBRIDGE_POOL"]),
            _rendered(templar, variables["NETWORK_ROLE_SUBNET_POOL"]),
            *[_rendered(templar, subnet) for subnet in excepted],
        ]
        seen: dict[str, None] = {}
        for cidr in ordered:
            seen.setdefault(cidr, None)
        return [list(seen)]
