from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR

ALERT_RULES_TEMPLATE = ("templates", "prometheus", "alert_rules.yml.j2")


class LookupModule(LookupBase):
    """
    Return a sorted list of deployed role IDs that ship their own Prometheus
    alert rules, i.e. every role in ``group_names`` that has a template at
    ``roles/<role_id>/templates/prometheus/alert_rules.yml.j2``.

    Keeps alert rules at the role that owns the metric instead of collecting
    them in web-app-prometheus: a role declares what "unhealthy" means for
    itself, and the Prometheus role only concatenates what the play enabled.

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
        group_names: list[str] = vars_.get("group_names", []) or []

        result = [
            role_id
            for role_id in sorted(set(group_names))
            if (ROLES_DIR / role_id).joinpath(*ALERT_RULES_TEMPLATE).exists()
        ]

        return [result]
