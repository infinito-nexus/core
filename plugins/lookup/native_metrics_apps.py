from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.cache.applications import get_merged_applications
from utils.roles.applications.config import get as get_app_conf


class LookupModule(LookupBase):
    """
    Return a sorted list of deployed application IDs that satisfy both:
      1. services.prometheus.native_metrics.enabled: true in their role config
      2. a prometheus.yml.j2 template at roles/<app_id>/templates/

    Used by web-app-prometheus/templates/configuration/prometheus.yml.j2 to auto-discover apps
    that expose a native /metrics endpoint without hardcoding each app name.

    Usage in a template:
      {% for app_id in lookup('native_metrics_apps') %}
      {% include 'roles/' + app_id + '/templates/prometheus.yml.j2' %}
      {% endfor %}

    'applications' is obtained via get_merged_applications — the same merged view
    that backs lookup('applications').
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        roles_dir = ROLES_DIR
        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir") or str(roles_dir),
            templar=getattr(self, "_templar", None),
        )

        group_names: list[str] = vars_.get("group_names", [])

        result: list[str] = []
        for app_id in sorted(applications.keys()):
            if app_id not in group_names:
                continue
            enabled = get_app_conf(
                applications=applications,
                application_id=app_id,
                config_path="services.prometheus.native_metrics.enabled",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
            if not enabled:
                continue

            scrape_template = roles_dir / app_id / "templates" / "prometheus.yml.j2"
            if scrape_template.exists():
                result.append(app_id)

        return [result]
