from __future__ import annotations

from typing import TYPE_CHECKING

from utils.storage.constrained import is_constrained, required_storage_bytes

if TYPE_CHECKING:
    from .compose import Compose


def detect_storage_constrained(
    compose: Compose, app_ids: list[str], variants: dict[str, int] | None = None
) -> bool:
    """
    Return True if the declared storage need of app_ids and their transitive
    dependencies, at the given variant overlay, exceeds the free space on the
    filesystem holding DockerRootDir.

    We intentionally measure the DockerRootDir filesystem because this is where
    images/volumes/build cache usually grow (especially in CI / Docker-in-Docker).
    """
    cmd = [
        "bash",
        "-lc",
        r"""
set -euo pipefail
root="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
if [ -z "${root}" ]; then
  root="/var/lib/docker"
fi

df -PB1 "${root}" | awk 'NR==2{print $4}'
""",
    ]

    r = compose.exec(cmd, check=False, capture=True)
    if r.returncode != 0:
        return False

    try:
        free_bytes = int((r.stdout or "").strip())
    except ValueError:
        return False

    return is_constrained(
        free_bytes=free_bytes,
        required_bytes=required_storage_bytes(app_ids, variants),
    )
