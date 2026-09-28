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

PROXY_ROLE = "svc-prx-openresty"

_CAST = {"cpus": float, "pids_limit": int}


class LookupModule(LookupBase):
    def _rendered(self, value: Any) -> str:
        """Return *value* as text, resolving it when it is still a template.

        A variable read out of the play's variables is raw, so a role whose
        ``application_id`` is itself a template (``sys-stk-full`` sets it from
        ``sys_stk_full_application_id``) hands back the unrendered string. An
        expression that names the same variable is templated before the lookup
        ever sees it, which is why the inline form this replaced never hit it.

        Args:
            value: the variable as the play holds it.
        """
        text = str(value or "")
        templar = getattr(self, "_templar", None)
        if templar is None or "{{" not in text:
            return text
        return str(templar.template(text))

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
        application_id = self._rendered(vars_.get("application_id"))
        service_name = self._rendered(vars_.get("service_name"))

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
