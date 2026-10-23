from __future__ import annotations

from utils.networks.mesh import awaited_keys, dialled_peers, handshaken, listens


class FilterModule:
    def filters(self):
        return {
            "mesh_awaited_keys": awaited_keys,
            "mesh_dialled_peers": dialled_peers,
            "mesh_handshaken": handshaken,
            "mesh_listens": listens,
        }
