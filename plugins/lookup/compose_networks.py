"""Lookup ``compose_networks``: emit the top-level ``networks:`` block for
a compose file. Reads the service_registry, the rendering role's
``application_id`` and ``DEPLOYMENT_MODE`` from variables.

Usage in any ``compose.yml.j2``:

    {{ lookup('compose_networks') }}

The output starts at column 0 (no caller-side indent).
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.render import render_compose_networks
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)
from utils.roles.entity_name import get_entity_name


def _resolve_var(templar, value: Any) -> Any:
    if templar is None:
        return value
    with contextlib.suppress(Exception):
        return templar.template(value)
    return value


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("compose_networks lookup takes no positional terms")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        application_id = _resolve_var(templar, vars_.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "compose_networks lookup: application_id is required in variables"
            )

        deployment_mode = str(
            _resolve_var(templar, vars_.get("DEPLOYMENT_MODE", "compose"))
        )

        swarm_cfg = _resolve_var(templar, vars_.get("swarm", {})) or {}
        swarm_encrypted = True
        net_cfg = swarm_cfg.get("network", {}) if isinstance(swarm_cfg, dict) else {}
        if isinstance(net_cfg, dict) and "encryption" in net_cfg:
            swarm_encrypted = bool(net_cfg.get("encryption"))

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]
        registry = build_service_registry_from_applications(applications)

        config_lookup = lookup_loader.get(
            "config", loader=self._loader, templar=templar
        )
        database_lookup = lookup_loader.get(
            "database", loader=self._loader, templar=templar
        )

        def _lookup_config(app: str, path: str, default: Any) -> Any:
            return config_lookup.run([app, path, default], variables=vars_)[0]

        def _lookup_database(app: str, key: str) -> Any:
            return database_lookup.run([app, key], variables=vars_)[0]

        rendered = render_compose_networks(
            application_id=str(application_id),
            deployment_mode=deployment_mode,
            registry=registry,
            get_entity_name=get_entity_name,
            lookup_config=_lookup_config,
            lookup_database=_lookup_database,
            swarm_encrypted=swarm_encrypted,
        )
        return [rendered]
