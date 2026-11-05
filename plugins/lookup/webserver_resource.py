"""The resource ceiling a webserver worker pool may assume.

``lookup('webserver_resource', key)`` is the smaller of the reverse proxy's
value for *key* and the current application's. A pool sized on either alone
over-commits whichever of the two containers is the tighter, and requests pass
through both.

``cpus`` resolves a percentage against the host first, so a proxy or an app
written as ``95%`` contributes its share rather than the literal text.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.resource_filter import resource_filter
from plugins.lookup.applications import LookupModule as ApplicationsLookup
from plugins.lookup.resource import LookupModule as ResourceLookup
from utils.templating.vars import resolve_var

PROXY_ROLE = "svc-prx-openresty"

_CAST = {"cpus": float, "pids_limit": int}


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('webserver_resource', key) expects exactly one term."
            )

        key = str(terms[0]).strip()
        cast = _CAST.get(key)
        if cast is None:
            raise AnsibleError(
                f"lookup('webserver_resource', {key!r}): expected one of "
                f"{sorted(_CAST)}"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        application_id = str(resolve_var(templar, vars_.get("application_id")) or "")
        service_name = str(resolve_var(templar, vars_.get("service_name")) or "")

        applications = ApplicationsLookup().run([], variables=vars_, **kwargs)[0]
        resource = ResourceLookup()
        hard_default = resource.run([key], variables=vars_, **kwargs)[0]

        scaling: dict[str, Any] = {}
        if key == "cpus":
            scaling["host_cpus"] = resource.run(
                ["host_cpus"], variables=vars_, **kwargs
            )[0]

        return [
            min(
                cast(
                    resource_filter(
                        applications,
                        app_id,
                        key,
                        service_name,
                        hard_default,
                        **scaling,
                    )
                )
                for app_id in (PROXY_ROLE, application_id)
            )
        ]
