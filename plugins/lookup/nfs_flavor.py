from __future__ import annotations

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """Resolved svc-storage-nfs-server flavor (kernel/ganesha): {{ lookup('nfs_flavor') }}.

    Reads the merged-config SPOT through lookup('config'); the dev/act->ganesha
    rule lives in meta/variants.yml.
    """

    def run(self, terms, variables=None, **kwargs):
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        config_lookup = lookup_loader.get(
            "config", loader=self._loader, templar=self._templar
        )
        return config_lookup.run(
            ["svc-storage-nfs-server", "services.nfs-server.flavor", "kernel"],
            variables=variables,
        )
