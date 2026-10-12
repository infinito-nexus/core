from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.config import get as get_app_conf
from utils.roles.mapping import ROLE_FILE_VARS_MAIN


def compose_mode_force(app_id: str) -> str:
    """Return the role's own deploy-mode override.

    Args:
        app_id: the role directory name.

    Returns:
        The literal ``compose_mode_force`` from the role's vars, or ``""`` when
        it is absent or a Jinja expression, which cannot be resolved from the
        scraping role's variable scope and so leaves the override invisible here.
    """
    path = ROLES_DIR / app_id / ROLE_FILE_VARS_MAIN
    if not path.is_file():
        return ""
    data = load_yaml_any(str(path), default_if_missing={})
    raw = data.get("compose_mode_force") if isinstance(data, Mapping) else None
    value = "" if raw is None else str(raw).strip()
    return "" if "{{" in value else value


class LookupModule(LookupBase):
    """
    Return a sorted list of deployed application IDs that satisfy all of:
      1. services.prometheus.native_metrics.enabled: true in their role config
      2. a prometheus.yml.j2 template at roles/<app_id>/templates/
      3. reachable from this prometheus: NOT on a node-local force_bridge
         network under swarm, which a swarm prometheus can neither join nor
         resolve, and NOT pinned to compose by its own compose_mode_force while
         the cluster runs swarm, which would make the scrape target name the
         wrong object. This is the single point that gates unreachable apps out
         of the native-metrics precreate + scrape.

    Used by web-app-prometheus/templates/configuration/prometheus.yml.j2 to auto-discover apps
    that expose a native /metrics endpoint without hardcoding each app name.

    Usage in a template:
      {% for app_id in lookup('native_metrics_apps') %}
      {% include 'roles/' + app_id + '/templates/prometheus.yml.j2' %}
      {% endfor %}

    'applications' is obtained via lookup('applications'), the merged-config SPOT.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        roles_dir = ROLES_DIR
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        group_names: list[str] = vars_.get("group_names", [])
        is_swarm = (
            str(self._templar.template(vars_["DEPLOYMENT_MODE"])).strip() == "swarm"
        )

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
            if not scrape_template.exists():
                continue

            force_bridge = get_app_conf(
                applications=applications,
                application_id=app_id,
                config_path="networks.local.force_bridge",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
            if is_swarm and bool(force_bridge):
                continue

            if is_swarm and compose_mode_force(app_id) == "compose":
                continue

            result.append(app_id)

        return [result]
