from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
)


class LookupModule(LookupBase):
    """
    Discover the role-local service registry.

    Usage:
      {{ query('service_registry') | first }}
      {{ query('service_registry', 'ordered') | first }}
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        roles_dir = Path(kwargs.get("roles_dir") or Path.cwd() / "roles")
        mode = str(terms[0]).strip() if terms else "mapping"

        if mode == "ordered":
            return [
                ordered_primary_service_entries(
                    build_service_registry_from_roles_dir(roles_dir), roles_dir
                )
            ]

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        registry = build_service_registry_from_applications(applications)

        if mode in {"mapping", ""}:
            return [registry]

        raise AnsibleError(
            f"service_registry: unsupported mode '{mode}' (expected 'mapping' or 'ordered')"
        )
