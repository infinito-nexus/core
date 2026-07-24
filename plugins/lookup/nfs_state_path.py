from __future__ import annotations

from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import STATE_SUBDIR, get_export_base, state_path


class LookupModule(LookupBase):
    """Cluster-shared NFS state dir: {{ lookup('nfs_state_path') }}."""

    def run(self, terms, variables=None, **kwargs):
        return [state_path(get_export_base(), STATE_SUBDIR)]
