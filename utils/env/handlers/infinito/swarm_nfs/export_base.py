"""INFINITO_SWARM_NFS_EXPORT_BASE: NFS export base inside the NFS-server
sidecar, read from the provider SPOT
roles/svc-storage-nfs-server/meta/services.yml."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.storage.nfs import get_export_base

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_SWARM_NFS_EXPORT_BASE"
COMMENT = "NFS export base path inside the NFS-server sidecar (SPOT: svc-storage-nfs-server services.yml)."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(KEY, get_export_base(), comment=COMMENT)
