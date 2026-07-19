from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """Exact deployed image references of every service whose ``backup.<marker>``
    is truthy and that carries an ``image`` or is ``custom``-built, for baudolo's
    exact ``--images-*`` matching.

    The ref is resolved via the ``image`` lookup, so it is byte-identical to the
    container's ``.Config.Image`` after deploy: swarm registry prefix included,
    and ``services.<key>.custom`` declarations resolve to the locally-built
    ``*_custom`` name exactly as the compose template deploys them. Image-less,
    non-custom shared references are skipped: their owner role carries the
    image and marker.

    Takes exactly one term: the backup marker key (e.g. ``no_stop_required`` or
    ``disabled``). Reads the live merged ``applications`` config.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "backup_image requires exactly one term: the backup marker key"
            )
        marker = str(terms[0])

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run([], variables=vars_)[0]

        image = lookup_loader.get(
            "image",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        )

        refs: set[str] = set()
        if isinstance(applications, Mapping):
            for application_id, app in applications.items():
                services = app.get("services") if isinstance(app, Mapping) else None
                if not isinstance(services, Mapping):
                    continue
                for service_key, svc in services.items():
                    backup = svc.get("backup") if isinstance(svc, Mapping) else None
                    if not (isinstance(backup, Mapping) and backup.get(marker)):
                        continue
                    if not (svc.get("image") or svc.get("custom")):
                        continue
                    ref = image.run(
                        [application_id, service_key],
                        variables=vars_,
                    )[0]
                    refs.add(ref)
        return [sorted(refs)]
