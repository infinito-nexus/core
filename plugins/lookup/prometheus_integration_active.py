from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """
    Return True when the prometheus monitoring block should be emitted for the
    current application on the current host; False otherwise.

    The condition satisfied:
      1. 'web-app-prometheus' is in group_names (prometheus is deployed on this host), AND
      2. Either the current application IS web-app-prometheus, OR it declares prometheus
         as an enabled compose service dependency (services.prometheus.enabled: true).

    Usage in a template:
      {% if lookup('prometheus_integration_active', application_id) %}
      ...prometheus monitoring block...
      {% endif %}

    Pass 'application_id' as term 0 (string). 'applications' is obtained via
    lookup('applications'), the merged-config SPOT.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[bool]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]

        # application_id may be passed explicitly (term 0) or read from available_variables.
        if terms and isinstance(terms[0], str):
            application_id: str = terms[0]
        else:
            application_id = vars_.get("application_id", "")

        group_names: list[str] = vars_.get("group_names", [])

        if "web-app-prometheus" not in group_names:
            return [False]

        if application_id == "web-app-prometheus":
            return [True]

        try:
            # Per services live at applications.<app>.services
            # (no `compose.services` wrapper).
            enabled = bool(
                applications.get(application_id, {})
                .get("services", {})
                .get("prometheus", {})
                .get("enabled", False)
            )
        except Exception:
            enabled = False

        return [enabled]
