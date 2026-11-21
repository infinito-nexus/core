from __future__ import annotations

import unittest

from utils.env.parser import parse_static_env
from utils.meta.scan import iter_subnets
from utils.networks.swarm_capacity import (
    lab_swarm_nodes,
    swarm_address_demand,
    usable_addresses,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_mode_enabled, get_role_placement

from . import PROJECT_ROOT, ROLES_DIR, load_role_meta

LAB_ENV = PROJECT_ROOT / "default.env"


class TestRoleSubnetSwarmCapacity(unittest.TestCase):
    def test_every_swarm_role_subnet_fits_its_stack(self) -> None:
        swarm_nodes = lab_swarm_nodes(parse_static_env(LAB_ENV))
        findings = []
        for role, subnet in sorted(iter_subnets(), key=lambda item: item[0]):
            role_dir = ROLES_DIR / role
            if not role_dir.is_dir():
                continue
            if not get_role_mode_enabled(role_dir, mode="swarm"):
                continue
            app_hosts = 1 if get_role_placement(role_dir) == "manager" else swarm_nodes
            demand, detail = swarm_address_demand(
                load_role_meta(role_dir / ROLE_FILE_META_SERVICES),
                app_hosts=app_hosts,
                swarm_nodes=swarm_nodes,
            )
            capacity = usable_addresses(subnet)
            if demand > capacity:
                findings.append(
                    f"- {role}: {subnet} holds {capacity} addresses, the stack "
                    f"needs at least {demand}: {detail}"
                )
        if findings:
            self.fail(
                "These roles declare a networks.local.subnet too small for their "
                f"swarm stack on {swarm_nodes} nodes:\n"
                + "\n".join(findings)
                + "\n\nFix: allocate a larger block with "
                "`infinito contributing network address suggest --clients <N>`, "
                "N at least the demand above plus room for rolling updates and "
                "reschedules."
            )


if __name__ == "__main__":
    unittest.main()
