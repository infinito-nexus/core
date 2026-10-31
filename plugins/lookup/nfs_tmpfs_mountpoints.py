from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import nested_tmpfs_mountpoints, volume_dir


class LookupModule(LookupBase):
    """Tmpfs mountpoints in NFS volumes: {{ lookup('nfs_tmpfs_mountpoints', ...) }}."""

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[dict[str, str]]]:
        """Return one list of ``{"path", "mode"}`` items, ``mode`` as an octal string.

        Args:
            terms: none.
            variables: the templating context; ``application_id`` is read from it.
            kwargs: ``volumes``, the rendered top-level compose ``volumes:`` mapping.
        """
        if terms:
            raise AnsibleError("nfs_tmpfs_mountpoints lookup expects no terms")
        if "volumes" not in kwargs:
            raise AnsibleError("nfs_tmpfs_mountpoints lookup requires 'volumes'")
        volumes = kwargs["volumes"]
        if not isinstance(volumes, Mapping):
            raise AnsibleError(
                "nfs_tmpfs_mountpoints: 'volumes' must be the compose volumes "
                f"mapping, got {type(volumes).__name__}"
            )

        vars_ = variables or self._templar.available_variables
        application_id = str(self._templar.template(vars_["application_id"])).strip()
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=self._templar
        ).run([], variables=vars_)[0]
        if application_id not in applications:
            raise AnsibleError(
                f"nfs_tmpfs_mountpoints: unknown application_id '{application_id}'"
            )

        nfs_dirs = {
            name: volume_dir(name, spec)
            for name, spec in volumes.items()
            if isinstance(spec, Mapping) and "driver_opts" in spec
        }
        try:
            mountpoints = nested_tmpfs_mountpoints(
                applications[application_id].get("volumes"), nfs_dirs
            )
        except (TypeError, ValueError) as exc:
            raise AnsibleError(
                f"nfs_tmpfs_mountpoints: {application_id}: {exc}"
            ) from exc
        return [
            [
                {"path": mountpoint["path"], "mode": f"0{mountpoint['mode']:o}"}
                for mountpoint in mountpoints
            ]
        ]
