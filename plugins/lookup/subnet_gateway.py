"""Lookup `subnet_gateway`: the gateway address of the role's local subnet.

Single SPOT for the address Docker assigns as the gateway of a role network,
used where a container has to reach the host side of its own bridge.

Example:

    {{ lookup('subnet_gateway') }}                # 192.168.24.1

Raises when the subnet is missing or holds no gateway, so an unusable network
fails at render time instead of reaching Docker as a malformed address.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.address import subnet_gateway
from utils.templating.vars import resolve_var


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("subnet_gateway lookup takes no positional terms")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        application_id = resolve_var(templar, vars_.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "subnet_gateway lookup: application_id is required in variables"
            )

        config_lookup = lookup_loader.get(
            "config", loader=self._loader, templar=templar
        )
        subnet = config_lookup.run(
            [str(application_id), "networks.local.subnet"], variables=vars_
        )[0]

        try:
            return [subnet_gateway(str(subnet))]
        except ValueError as exc:
            raise AnsibleError(
                f"subnet_gateway lookup for '{application_id}': {exc}"
            ) from exc
