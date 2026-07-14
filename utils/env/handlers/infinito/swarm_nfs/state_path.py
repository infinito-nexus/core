"""INFINITO_SWARM_NFS_STATE_PATH: cluster-shared NFS state dir for the
act-swarm test harness, derived from the export-base SPOT
(INFINITO_SWARM_NFS_EXPORT_BASE) and the shared state subdir constant."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.storage.nfs import STATE_SUBDIR, state_path

if TYPE_CHECKING:
    from utils.env.builder import BuildContext, EnvBuilder

KEY = "INFINITO_SWARM_NFS_STATE_PATH"
COMMENT = "Cluster-shared NFS state dir on the act-swarm test nodes."


def apply(eb: EnvBuilder, ctx: BuildContext) -> None:
    eb.set(
        KEY,
        state_path(eb.get("INFINITO_SWARM_NFS_EXPORT_BASE"), STATE_SUBDIR),
        comment=COMMENT,
    )
