from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import mount_opts


class LookupModule(LookupBase):
    """NFS mount options: {{ lookup('nfs_mount_opts') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        nfs = variables.get("storage", {}).get("nfs", {})
        return [mount_opts(nfs.get("version", 4), variables.get("RUNTIME", "host"))]
