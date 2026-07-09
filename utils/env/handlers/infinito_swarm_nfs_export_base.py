"""INFINITO_SWARM_NFS_EXPORT_BASE: NFS export base inside the NFS-server
sidecar, read from the deploy SPOT group_vars/all/15_storage.yml
(storage.nfs.export_base)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_SWARM_NFS_EXPORT_BASE"
COMMENT = "NFS export base path inside the NFS-server sidecar (SPOT: group_vars/all/15_storage.yml)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    storage = load_yaml_any("group_vars/all/15_storage.yml")
    eb.set(KEY, storage["storage"]["nfs"]["export_base"], comment=COMMENT)
