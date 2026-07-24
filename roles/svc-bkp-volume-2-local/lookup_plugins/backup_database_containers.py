from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """Container names (``services.<key>.name``) of every service whose
    ``backup.database_routine`` is truthy, for baudolo ``--database-containers``.

    Reads the live merged ``applications`` config; takes no terms.
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

        names: set[str] = set()
        if isinstance(applications, Mapping):
            for app in applications.values():
                services = app.get("services") if isinstance(app, Mapping) else None
                if not isinstance(services, Mapping):
                    continue
                for svc in services.values():
                    backup = svc.get("backup") if isinstance(svc, Mapping) else None
                    if isinstance(backup, Mapping) and backup.get("database_routine"):
                        name = svc.get("name")
                        if name:
                            names.add(name)
        return [sorted(names)]
