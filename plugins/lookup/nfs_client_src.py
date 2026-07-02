from __future__ import annotations

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import client_src, state_path


class LookupModule(LookupBase):
    """NFS client mount src (server:path): {{ lookup('nfs_client_src') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        nfs = variables.get("storage", {}).get("nfs", {})
        flavor = lookup_loader.get(
            "nfs_flavor", loader=self._loader, templar=self._templar
        ).run([], variables=variables)[0]
        state = state_path(
            nfs.get("export_base"), variables.get("STORAGE_NFS_STATE_SUBDIR")
        )
        return [client_src(nfs.get("server"), nfs.get("version", 4), flavor, state)]
