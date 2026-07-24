from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import fstype, get_client_version


class LookupModule(LookupBase):
    """NFS mount fstype (nfs4/nfs): {{ lookup('nfs_fstype') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        return [fstype(get_client_version())]
