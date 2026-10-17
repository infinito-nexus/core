from __future__ import annotations

from utils.networks.mesh import dialled_peers, listens


class FilterModule:
    def filters(self):
        return {
            "mesh_dialled_peers": dialled_peers,
            "mesh_listens": listens,
        }
