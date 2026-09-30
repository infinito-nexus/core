"""Lookup ``native_metrics_target``: scrape target for an app that exposes its
own metrics port. Reads ``services.prometheus.native_metrics`` for the service
key and port, then delegates host resolution to ``scrape_target`` so swarm and
compose stay on one implementation.

Usage in a per-app prometheus.yml.j2 fragment:
  targets: ["{{ lookup('native_metrics_target', native_prometheus_application_id) }}"]
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms:
            raise AnsibleError(
                "native_metrics_target lookup requires the application_id term"
            )

        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError("native_metrics_target: application_id must be non-empty")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        def conf(key: str) -> str:
            value = get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.prometheus.native_metrics.{key}",
                strict=False,
                default="",
            )
            return "" if value is None else str(value).strip()

        port = conf("port")
        if not port:
            raise AnsibleError(
                "native_metrics_target: no "
                f"services.prometheus.native_metrics.port for {application_id!r}"
            )

        service_key = conf("service_key") or get_entity_name(application_id)
        if not service_key:
            raise AnsibleError(
                f"native_metrics_target: cannot derive service key for {application_id!r}"
            )

        return lookup_loader.get(
            "scrape_target", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([application_id, service_key], variables=vars_, port=port)
