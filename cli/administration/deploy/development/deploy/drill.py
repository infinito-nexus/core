"""Recover drill between the sync and async pass of the first round."""

from __future__ import annotations

import os

from cli.administration.deploy.development.mirrors import CONTAINER_REPO_ROOT


def _maybe_recover_drill(compose, plan_index: int) -> None:
    """Verify recovery between PASS 1 and PASS 2 of the first round: seed a
    backup tree and `recover full` it back on this single host. Gated by
    INFINITO_RECOVER_DRILL (off by default); raises on drill failure so the
    deploy fails fast before the async pass. Host mode is exempt: the drill
    verifies container backup trees, which host roles do not produce."""
    if plan_index != 0:
        return
    if (os.environ.get("INFINITO_RECOVER_DRILL") or "").strip().lower() != "true":
        return
    if (os.environ.get("INFINITO_DEPLOY_MODE") or "").strip().lower() == "host":
        return
    print("=== recover drill (backup/recover verification between passes) ===")
    drill_script = (
        CONTAINER_REPO_ROOT / "scripts" / "tests" / "deploy" / "ci" / "recover_drill.sh"
    )
    compose.exec(
        ["bash", str(drill_script)],
        extra_env={"INFINITO_REPO_ROOT": str(CONTAINER_REPO_ROOT)},
        live=True,
    )
