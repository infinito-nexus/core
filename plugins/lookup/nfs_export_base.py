from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import get_export_base


class LookupModule(LookupBase):
    """NFS export base from the provider SPOT: {{ lookup('nfs_export_base') }}."""

    def run(self, terms, variables=None, **kwargs):
        return [get_export_base()]
