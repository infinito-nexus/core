from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """Docker volume names of every ``meta/volumes.yml`` entry that declares
    ``backup: false``, for baudolo's ``--volumes-no-backup-required``.

    The emitted name is the entry's pinned ``name:``, which is what
    ``docker volume ls`` reports and what baudolo matches. Exclusion is
    per volume, not per image: a container may legitimately hold one
    derived tree next to the state that must be preserved.

    Reads the live merged ``applications`` config, whose payload carries the
    canonical volumes of every deployed role. Takes no terms.
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
                volumes = app.get("volumes") if isinstance(app, Mapping) else None
                if not isinstance(volumes, Mapping):
                    continue
                for semantic_name, entry in volumes.items():
                    if not isinstance(entry, Mapping):
                        continue
                    if entry.get("backup") is not False:
                        continue
                    name = entry.get("name") or semantic_name
                    if isinstance(name, str) and name:
                        names.add(name)
        return [sorted(names)]
