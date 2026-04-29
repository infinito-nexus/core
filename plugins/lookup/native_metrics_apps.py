from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.config import get as get_app_conf
from utils.cache.applications import get_merged_applications


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
        terms: List[Any],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[List[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        roles_dir = self._find_roles_dir()
        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir") or str(roles_dir),
            templar=getattr(self, "_templar", None),
        )

        group_names: List[str] = vars_.get("group_names", [])

        result: List[str] = []
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

    def _find_roles_dir(self) -> Path:
        candidates = [
            Path(os.getcwd()) / "roles",
            Path(__file__).resolve().parent.parent.parent / "roles",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        raise AnsibleError("native_metrics_apps: cannot locate roles/ directory")
