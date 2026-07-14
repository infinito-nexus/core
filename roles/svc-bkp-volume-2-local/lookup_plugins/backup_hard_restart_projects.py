from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    """Compose project (entity) names of every application with at least one
    service whose ``backup.project_hard_restart`` is truthy, for baudolo
    ``--hard-restart-projects``.

    The entity name equals ``os.path.basename(compose_dir)``, which baudolo
    matches against the project list. Reads the live merged ``applications``
    config; takes no terms.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]

        entities: set[str] = set()
        if isinstance(applications, Mapping):
            for application_id, app in applications.items():
                services = app.get("services") if isinstance(app, Mapping) else None
                if not isinstance(services, Mapping):
                    continue
                for svc in services.values():
                    backup = svc.get("backup") if isinstance(svc, Mapping) else None
                    if isinstance(backup, Mapping) and backup.get(
                        "project_hard_restart"
                    ):
                        entities.add(get_entity_name(application_id))
                        break
        return [sorted(entities)]
