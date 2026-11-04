from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity.name import entity_name
from utils.storage.nfs import swarm_nfs_backed


def deployed_volume_name(
    application_id: str, semantic_name: str, entry: Mapping
) -> str:
    """Return the name ``docker volume ls`` reports for a ``meta/volumes.yml`` entry.

    ``compose_volumes`` writes a ``name:`` into the stack only when the entry
    pins one; otherwise the semantic key stands alone and the engine prefixes
    it with the project, which is the role's entity name. Emitting the bare
    key for such an entry hands baudolo a name that matches no volume, and the
    exclusion silently does nothing.

    Args:
        application_id: the role the entry belongs to.
        semantic_name: the entry's key in ``meta/volumes.yml``.
        entry: the entry itself.
    """
    pinned = entry.get("name")
    if isinstance(pinned, str) and pinned:
        return pinned
    entity = entity_name(application_id)
    return f"{entity}_{semantic_name}" if entity else semantic_name


class LookupModule(LookupBase):
    """Docker volume names baudolo must not copy, for its
    ``--volumes-no-backup-required``.

    Two sources feed the list: every ``meta/volumes.yml`` entry that declares
    ``backup: false``, and - in swarm mode with NFS storage - every volume the
    swarm NFS rewrite backs with the shared export. The latter are captured by
    ``svc-bkp-nfs-2-local`` on the export host; copying them here again reads
    the same bytes through the NFS mount, doubling the backup tree and racing
    the export-side generation (see the role README's source-of-truth rule).

    The cluster mode is read here; a role's own ``compose_mode_force`` override
    is resolved per role inside the predicate, because this lookup answers for
    every deployed role at once and one ambient value cannot speak for all.

    The NFS exclusion only applies when ``svc-bkp-nfs-2-local`` is actually
    deployed. It enters a play by inventory group membership alone, and
    ``svc-storage-nfs-server`` ships a variant that runs without it, so an
    export whose repository nobody deployed must keep its volumes here rather
    than lose them from both capture paths.

    The emitted name is what ``docker volume ls`` reports and what baudolo
    matches: the entry's pinned ``name:``, or the project-prefixed semantic
    key when it pins none (see ``deployed_volume_name``). Exclusion is
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

        templar = getattr(self, "_templar", None)
        deployment_mode = vars_.get("DEPLOYMENT_MODE", "")
        storage = vars_.get("storage")
        if templar is not None:
            with contextlib.suppress(Exception):
                deployment_mode = templar.template(deployment_mode)
            with contextlib.suppress(Exception):
                storage = templar.template(storage)
        deployment_mode = str(deployment_mode or "")
        storage_backend = ""
        if isinstance(storage, Mapping):
            storage_backend = str(storage.get("backend") or "")
        groups = vars_.get("groups")
        export_repo = bool(
            isinstance(groups, Mapping) and groups.get("svc-bkp-nfs-2-local")
        )

        names: set[str] = set()
        if isinstance(applications, Mapping):
            for app_id, app in applications.items():
                volumes = app.get("volumes") if isinstance(app, Mapping) else None
                if not isinstance(volumes, Mapping):
                    continue
                for semantic_name, entry in volumes.items():
                    if not isinstance(entry, Mapping):
                        continue
                    excluded = entry.get("backup") is False or (
                        export_repo
                        and entry.get("type", "volume") == "volume"
                        and swarm_nfs_backed(
                            entry,
                            application_id=str(app_id),
                            deployment_mode=deployment_mode,
                            storage_backend=storage_backend,
                        )
                    )
                    if not excluded:
                        continue
                    name = deployed_volume_name(str(app_id), str(semantic_name), entry)
                    if isinstance(name, str) and name:
                        names.add(name)
        return [sorted(names)]
