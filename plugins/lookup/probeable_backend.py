"""Return whether an application has a backend a vhost can probe.

True when a port exists for ``resolve_upstream`` to build an upstream from:
the local one outside swarm, the internal one inside it. Asking that lookup
for a role that has neither raises rather than returning empty.

Usage in a template::

    {% if lookup('probeable_backend', application_id) %}
    ...health probe against the app's own backend...
    {% endif %}

Pass ``application_id`` as term 0, defaulting to the templating variable of the
same name. ``http_port`` and ``proxy_internal_port`` are read from the same
variables, so a role that resolved its port itself is not reported as
backendless. ``applications`` comes from ``lookup('applications')``, the
merged-config SPOT.
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name

PORT_SCOPES = ("local", "internal")


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[bool]:
        """Return ``[True]`` when a port exists to probe, ``[False]`` otherwise.

        Args:
            terms: term 0 is the application id.
            variables: templating variables.
            kwargs: unused.
        """
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        if vars_.get("http_port") or vars_.get("proxy_internal_port"):
            return [True]

        if terms and isinstance(terms[0], str):
            application_id = terms[0]
        else:
            application_id = vars_.get("application_id", "")
        if not application_id:
            return [False]

        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]

        entity = get_entity_name(application_id)
        ports = (
            applications.get(application_id, {})
            .get("services", {})
            .get(entity, {})
            .get("ports", {})
        )
        if not isinstance(ports, dict):
            return [False]

        return [
            any(
                (ports.get(scope) or {}).get("http")
                for scope in PORT_SCOPES
                if isinstance(ports.get(scope), dict)
            )
        ]
