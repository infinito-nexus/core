from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import state_path


class LookupModule(LookupBase):
    """Cluster-shared NFS state dir: {{ lookup('nfs_state_path') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        nfs = variables.get("storage", {}).get("nfs", {})
        return [
            state_path(
                nfs.get("export_base"), variables.get("STORAGE_NFS_STATE_SUBDIR")
            )
        ]
