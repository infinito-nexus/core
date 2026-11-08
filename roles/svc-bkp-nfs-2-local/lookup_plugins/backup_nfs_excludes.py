from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import STATE_SUBDIR, backup_disabled_dirs


class LookupModule(LookupBase):
    """Export-relative directories of the NFS-backed volumes declared
    ``backup: false``, for the export rsync's ``--exclude`` list.

    Args:
        terms: none.
        variables: the play variables; ``DEPLOYMENT_MODE`` and ``storage``
            decide which volumes the swarm NFS rewrite puts on the export, and
            the live merged ``applications`` config is read through them.

    Returns:
        One list: the sorted ``<state subdir>/<volume dir>`` paths.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]

        deployment_mode = vars_.get("DEPLOYMENT_MODE", "")
        storage = vars_.get("storage")
        if templar is not None:
            with contextlib.suppress(Exception):
                deployment_mode = templar.template(deployment_mode)
            with contextlib.suppress(Exception):
                storage = templar.template(storage)
        storage_backend = ""
        if isinstance(storage, Mapping):
            storage_backend = str(storage.get("backend") or "")

        if not isinstance(applications, Mapping):
            return [[]]
        dirs = backup_disabled_dirs(
            applications,
            deployment_mode=str(deployment_mode or ""),
            storage_backend=storage_backend,
        )
        return [[f"{STATE_SUBDIR}/{name}" for name in dirs]]
