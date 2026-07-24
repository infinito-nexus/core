"""Lookup ``compose_external_networks``: the provider role ids whose overlay
the compose file of ``application_id`` references as ``external: true``.

Usage:

    {{ lookup('compose_external_networks') }}

Returns a list of role ids (e.g. ``svc-db-redis``), matching the
``external: true`` entries ``compose_networks`` emits. The swarm deploy
handler pre-creates those overlays so a shared provider's network is present
even when the provider role did not run in the same play.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.render import compute_external_network_roles
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)


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
    ) -> list[Any]:
        if terms:
            raise AnsibleError(
                "compose_external_networks lookup takes no positional terms"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        application_id = _resolve_var(templar, vars_.get("application_id"))
        if not application_id:
            raise AnsibleError(
                "compose_external_networks lookup: application_id is required in variables"
            )

        deployment_mode = str(
            _resolve_var(templar, vars_.get("DEPLOYMENT_MODE", "compose"))
        )

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

        roles = compute_external_network_roles(
            application_id=str(application_id),
            deployment_mode=deployment_mode,
            registry=registry,
            lookup_config=_lookup_config,
            lookup_database=_lookup_database,
        )
        return [roles]
