from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """Exact deployed image references of every service whose ``backup.<marker>``
    equals the wanted boolean and that carries an ``image`` or is
    ``custom``-built, for baudolo's exact ``--images-*`` matching.

    The ref is resolved via the ``image`` lookup, so it is byte-identical to the
    container's ``.Config.Image`` after deploy: swarm registry prefix included,
    and ``services.<key>.custom`` declarations resolve to the locally-built
    ``*_custom`` name exactly as the compose template deploys them. Image-less,
    non-custom shared references are skipped: their owner role carries the
    image and marker.

    Args:
        terms: exactly two, the backup marker key (e.g. ``stop_required`` or
            ``disabled``) and the boolean the marker must equal (e.g. ``false``
            for the images baudolo may copy live, ``true`` for the images it
            must skip).
        variables: the play variables; the live merged ``applications``
            config is read through them.

    Returns:
        One list: the sorted, de-duplicated image references.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "backup_image requires exactly two terms: the backup marker key "
                "and the boolean it must equal"
            )
        marker, wanted = terms
        if not isinstance(wanted, bool):
            raise AnsibleError(
                f"backup_image: the wanted value of '{marker}' must be a boolean, "
                f"got {wanted!r}"
            )
        marker = str(marker)

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
                    if not isinstance(backup, Mapping):
                        continue
                    if backup.get(marker) is not wanted:
                        continue
                    if not (svc.get("image") or svc.get("custom")):
                        continue
                    ref = image.run(
                        [application_id, service_key],
                        variables=vars_,
                    )[0]
                    refs.add(ref)
        return [sorted(refs)]
