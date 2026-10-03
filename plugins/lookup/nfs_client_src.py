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
    """NFS client mount src (server:path): {{ lookup('nfs_client_src') }}.

    Pass ``controller`` to address the server as the Ansible controller must
    reach it: ``{{ lookup('nfs_client_src', 'controller') }}``. Where the
    cluster is joined by a VPN the controller is not a member of, the two are
    different addresses, and the controller can only use the underlay one.
    """

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        nfs = variables.get("storage", {}).get("nfs", {})
        server = nfs.get("server")
        if terms and terms[0] == "controller":
            server = nfs.get("controller_server") or server
        flavor = lookup_loader.get(
            "nfs_flavor", loader=self._loader, templar=self._templar
        ).run([], variables=variables)[0]
        state = state_path(get_export_base(), STATE_SUBDIR)
        return [client_src(server, get_client_version(), flavor, state)]
