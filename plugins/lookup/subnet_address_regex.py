"""Lookup `subnet_address_regex`: match any address in the role's local subnet.

Single SPOT for turning `networks.local.subnet` into an address matcher. A swarm
task carries an address on every network it joins, all of them site-local, so a
service that must bind to one of them needs this rather than a generic
"site-local" selector.

Example:

    {{ lookup('subnet_address_regex') }}          # 192\\.168\\.24\\.\\d+

Raises when the subnet is missing or its prefix is not octet-aligned, so a
topology this cannot express fails at render time instead of binding silently
to the wrong network.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.address import subnet_address_regex


def _resolve_var(templar: Any, value: Any) -> Any:
    if templar is not None and value is not None:
        with contextlib.suppress(Exception):
            return templar.template(value)
    return value


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("subnet_address_regex lookup takes no positional terms")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        application_id = _resolve_var(templar, vars_.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "subnet_address_regex lookup: application_id is required in variables"
            )

        config_lookup = lookup_loader.get(
            "config", loader=self._loader, templar=templar
        )
        subnet = config_lookup.run(
            [str(application_id), "networks.local.subnet"], variables=vars_
        )[0]

        try:
            return [subnet_address_regex(str(subnet))]
        except ValueError as exc:
            raise AnsibleError(
                f"subnet_address_regex lookup for '{application_id}': {exc}"
            ) from exc
