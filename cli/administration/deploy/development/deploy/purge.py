"""Per-app entity purge between matrix-deploy rounds."""

from __future__ import annotations

import os
import subprocess

from cli.administration.deploy.development import PROJECT_ROOT


def _purge_app_entities(*, container: str, app_ids: list[str]) -> None:
    """Run the per-app cleanup script for every app from the previous
    matrix-deploy round before the next round starts.

    `scripts/tests/deploy/local/purge/entity.sh` removes the
    application's containers, networks, and Ansible-managed state on
    the host so the next round boots from a clean slate. Failures are
    surfaced (the matrix MUST NOT silently mix variant state across
    rounds).
    """
    if not app_ids:
        return
    repo_root = PROJECT_ROOT
    purge_script = (
        repo_root / "scripts" / "tests" / "deploy" / "local" / "purge" / "entity.sh"
    )
    env = os.environ.copy()
    env["apps"] = ",".join(app_ids)
    env["INFINITO_CONTAINER"] = container
    print(
        "=== matrix-deploy: purging entities between rounds for "
        f"{', '.join(app_ids)} ==="
    )
    subprocess.run(
        ["bash", str(purge_script)],
        cwd=str(repo_root),
        env=env,
        check=True,
    )
