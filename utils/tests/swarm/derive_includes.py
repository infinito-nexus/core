#!/usr/bin/env python3
"""Print, one per line, the role IDs the provision CLI should
``--include`` so the resulting inventory has every group APP_ID's
transitive deps will need at deploy time.

``svc-swarm-manager`` (subset marker),
``svc-storage-nfs-client`` (no ``application_id``) and
``svc-registry-docker`` (consumed by the swarm handler that pushes
locally-built images, but not declared as a meta-dep so it stays
out of compose-mode deploys) are added explicitly because the
dep-walker only knows roles that are in the ``applications`` dict.

Input (env): ``APP_ID``.
"""

from __future__ import annotations

import os
import sys

from utils import PROJECT_ROOT
from utils.cache.applications import get_merged_applications
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps

_ROLES_DIR = PROJECT_ROOT / "roles"

_EXPLICIT_INCLUDES: tuple[str, ...] = (
    "svc-swarm-manager",
    "svc-storage-nfs-client",
    "svc-registry-docker",
)


def derive_includes(app_id: str) -> list[str]:
    applications = get_merged_applications(roles_dir=str(_ROLES_DIR))
    transitive = applications_if_group_and_all_deps(
        applications,
        [app_id],
        project_root=str(PROJECT_ROOT),
        roles_dir=str(_ROLES_DIR),
    )
    found = set(transitive) | set(_EXPLICIT_INCLUDES) | {app_id}
    return sorted(found)


def main() -> int:
    for role_id in derive_includes(os.environ["APP_ID"]):
        print(role_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
