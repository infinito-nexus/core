"""Lookup ``container_networks``: emit the per-service ``networks:``
attachment block. Reads the service_registry plus ``application_id`` and
``DEPLOYMENT_MODE`` from variables.

Usage inside a service block in ``compose.yml.j2``:

    {{ lookup('container_networks') }}

The output is pre-indented by 4 spaces so it sits cleanly under a
``services.<svc>`` block.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.render import render_container_networks
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)
from utils.roles.entity.name import get_entity_name


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
            raise AnsibleError("container_networks lookup takes no positional terms")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        application_id = _resolve_var(templar, vars_.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "container_networks lookup: application_id is required in variables"
            )

        mode_force = _resolve_var(templar, vars_.get("compose_mode_force", ""))
        deployment_mode = str(
            mode_force or _resolve_var(templar, vars_.get("DEPLOYMENT_MODE", "compose"))
        ).strip()
        provider_self_alias = bool(kwargs.get("provider_self_alias", True))

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

        rendered = render_container_networks(
            application_id=str(application_id),
            deployment_mode=deployment_mode,
            registry=registry,
            get_entity_name=get_entity_name,
            lookup_config=_lookup_config,
            lookup_database=_lookup_database,
            provider_self_alias=provider_self_alias,
            node_local=bool(kwargs.get("node_local", False)),
        )
        return [rendered]
