"""Lookup ``scrape_target``: mode-aware ``<host>:<port>`` for a Prometheus
scrape target. Swarm resolves ``tasks.<entity>_<service_key>`` (per-task DNS);
compose uses ``compose_host`` or the service container name."""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.entity.name import get_entity_name


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms:
            raise AnsibleError("scrape_target lookup requires the application_id term")

        application_id = _as_str(terms[0])
        if not application_id:
            raise AnsibleError("scrape_target: application_id must be non-empty")

        service_key = _as_str(terms[1]) if len(terms) > 1 else ""
        if not service_key:
            raise AnsibleError("scrape_target: service_key must be non-empty")

        port_kind = (
            _as_str(terms[2]) if len(terms) > 2 else _as_str(kwargs.get("port_kind"))
        ) or "http"
        compose_host = (
            _as_str(terms[3]) if len(terms) > 3 else _as_str(kwargs.get("compose_host"))
        )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)
        deployment_mode = str(raw_mode).strip()

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        port = _as_str(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{service_key}.ports.internal.{port_kind}",
                strict=False,
                default="",
            )
        )
        if not port:
            raise AnsibleError(
                f"scrape_target: no internal port for {application_id!r} "
                f"(services.{service_key}.ports.internal.{port_kind})"
            )

        if deployment_mode == "swarm":
            entity = get_entity_name(application_id)
            if not entity:
                raise AnsibleError(
                    f"scrape_target: cannot derive entity from {application_id!r}"
                )
            return [f"tasks.{entity}_{service_key}:{port}"]

        host = compose_host or _as_str(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{service_key}.name",
                strict=False,
                default="",
            )
        )
        if not host:
            raise AnsibleError(
                f"scrape_target: no compose host for {application_id!r} "
                f"(services.{service_key}.name)"
            )
        return [f"{host}:{port}"]
