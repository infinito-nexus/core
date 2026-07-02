from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import fstype


class LookupModule(LookupBase):
    """NFS mount fstype (nfs4/nfs): {{ lookup('nfs_fstype') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        version = variables.get("storage", {}).get("nfs", {}).get("version", 4)
        return [fstype(version)]
