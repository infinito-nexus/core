"""Lint: driver (``drv-*``) roles must opt out of swarm test-deploys.

Hardware/driver roles configure the host (kernel modules, lid switch, vendor
drivers); they are meaningless as swarm services and must not enter the swarm
deploy matrix. Every ``roles/drv-*`` role therefore MUST set
``modes.swarm.enabled: false`` on its ``meta/services.yml`` primary entity
(the discovery opt-out honored by ``--skip-mode swarm``). Compose is
intentionally NOT required here -- drivers still run in compose deploys.
"""

from __future__ import annotations

import unittest

from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_skip

from . import PROJECT_ROOT

_DRV_GLOB = "drv-*"


class TestDrvRolesSkipSwarm(unittest.TestCase):
    def test_every_drv_role_skips_swarm(self) -> None:
        offenders = []
        for role_dir in sorted((PROJECT_ROOT / "roles").glob(_DRV_GLOB)):
            if not (role_dir / ROLE_FILE_META_SERVICES).is_file():
                continue
            if "swarm" not in get_role_skip(role_dir):
                offenders.append(role_dir.name)

        if offenders:
            self.fail(
                f"{len(offenders)} drv-* role(s) do not disable swarm in their "
                "meta/services.yml modes: " + ", ".join(offenders) + ". "
                "Driver roles must not be swarm-deployed: set\n"
                "  modes:\n    swarm:\n      enabled: false\n"
                "on each role's primary service entity."
            )


if __name__ == "__main__":
    unittest.main()
