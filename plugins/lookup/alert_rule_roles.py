from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR

ALERT_RULES_TEMPLATE = ("templates", "prometheus", "alert_rules.yml.j2")


class LookupModule(LookupBase):
    """
    Return a sorted list of role IDs whose Prometheus alert rules belong in
    this deploy: every role that ships a template at
    ``roles/<role_id>/templates/prometheus/alert_rules.yml.j2`` and is actually
    scraped, i.e. appears in ``native_metrics_apps``.

    Keeps alert rules at the role that owns the metric instead of collecting
    them in web-app-prometheus: a role declares what "unhealthy" means for
    itself, and the Prometheus role only concatenates what the play enabled.

    Filtering on activation here rather than inside each fragment is what keeps
    the fragments free of boilerplate. A rule that fires on a series nothing
    scrapes is worse than no rule: it alerts on ``absent()`` forever.

    Usage in a template:
      {% for role_id in lookup('alert_rule_roles') %}
      {% include 'roles/' + role_id + '/templates/prometheus/alert_rules.yml.j2' %}
      {% endfor %}

    The rendered fragment MUST start at the ``groups:`` item level (two-space
    indented ``- name: <group>`` entries), because it is concatenated into the
    single ``groups:`` list of the Prometheus rule file.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if terms:
            raise ValueError("alert_rule_roles lookup takes no positional terms")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        scraped: list[str] = lookup_loader.get(
            "native_metrics_apps",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]

        result = [
            role_id
            for role_id in sorted(set(scraped))
            if (ROLES_DIR / role_id).joinpath(*ALERT_RULES_TEMPLATE).exists()
        ]

        return [result]
