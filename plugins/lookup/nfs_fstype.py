from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import fstype, get_client_version


class LookupModule(LookupBase):
    """NFS mount fstype (nfs4/nfs): {{ lookup('nfs_fstype') }}."""

    def run(self, terms, variables=None, **kwargs):
        return [fstype(get_client_version())]
