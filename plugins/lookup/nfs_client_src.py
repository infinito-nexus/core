from __future__ import annotations

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.storage.nfs import (
    STATE_SUBDIR,
    client_src,
    get_client_version,
    get_export_base,
    state_path,
)


class LookupModule(LookupBase):
    """NFS client mount src (server:path): {{ lookup('nfs_client_src') }}."""

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        nfs = variables.get("storage", {}).get("nfs", {})
        flavor = lookup_loader.get(
            "nfs_flavor", loader=self._loader, templar=self._templar
        ).run([], variables=variables)[0]
        state = state_path(get_export_base(), STATE_SUBDIR)
        return [client_src(nfs.get("server"), get_client_version(), flavor, state)]
