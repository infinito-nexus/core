from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import get_client_version, mount_opts


class LookupModule(LookupBase):
    """NFS mount options: {{ lookup('nfs_mount_opts') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        return [mount_opts(get_client_version(), variables.get("RUNTIME", "host"))]
