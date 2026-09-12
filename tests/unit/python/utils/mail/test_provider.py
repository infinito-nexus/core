"""The mail provider a deploy actually resolves to.

``MAIL_PROVIDER`` is the operator's flag and wins whenever the role it names is
deployed. The fallback exists for the round that deploys only the alternative
provider, and it must stay single-valued: if two roles could both consider
themselves active they would both bind the public SMTP ports.
"""

from __future__ import annotations

import unittest

from utils.mail.provider import (
    declaring_roles,
    deployed_roles,
    resolve_active_provider,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

STALWART = "web-app-stalwart"
MAILU = "web-app-mailu"


class TestDeclaringRoles(unittest.TestCase):
    def test_both_providers_are_discovered(self):
        roles = declaring_roles(ROLES_DIR)
        self.assertIn(STALWART, roles)
        self.assertIn(MAILU, roles)

    def test_provides_outranks_covers(self):
        roles = declaring_roles(ROLES_DIR)
        self.assertLess(
            roles.index(STALWART),
            roles.index(MAILU),
            "the role declaring provides: email must win the fallback",
        )


class TestResolveActiveProvider(unittest.TestCase):
    def test_configured_provider_wins_when_deployed(self):
        self.assertEqual(
            resolve_active_provider(STALWART, [STALWART, MAILU], ROLES_DIR), STALWART
        )

    def test_configured_provider_wins_alone(self):
        self.assertEqual(
            resolve_active_provider(STALWART, [STALWART], ROLES_DIR), STALWART
        )

    def test_falls_back_to_the_provider_that_is_deployed(self):
        self.assertEqual(resolve_active_provider(STALWART, [MAILU], ROLES_DIR), MAILU)

    def test_mailu_configured_wins_over_stalwart_priority(self):
        self.assertEqual(
            resolve_active_provider(MAILU, [STALWART, MAILU], ROLES_DIR), MAILU
        )

    def test_exactly_one_provider_is_active_when_both_deployed(self):
        deployed = [STALWART, MAILU]
        for configured in (STALWART, MAILU, "web-app-absent"):
            active = resolve_active_provider(configured, deployed, ROLES_DIR)
            others = [r for r in deployed if r != active]
            self.assertNotIn(
                active,
                others,
                f"configured={configured!r} produced more than one active provider",
            )
            self.assertIn(active, deployed)

    def test_no_provider_deployed_keeps_the_configured_value(self):
        self.assertEqual(
            resolve_active_provider(STALWART, ["web-app-gitea"], ROLES_DIR), STALWART
        )

    def test_empty_group_names_keeps_the_configured_value(self):
        self.assertEqual(resolve_active_provider(STALWART, [], ROLES_DIR), STALWART)


class TestDeployedRoles(unittest.TestCase):
    """Resolution is cluster-wide, so it reads ``groups``, not ``group_names``.

    A swarm worker's ``group_names`` lacks the manager-pinned provider. Deriving
    presence per-host would give workers a different provider than the manager
    and render their relay config against a server they must not use.
    """

    def test_only_groups_with_hosts_count_as_deployed(self):
        groups = {
            STALWART: ["mgr-01"],
            MAILU: [],
            "all": ["mgr-01", "wrk-01"],
        }
        result = deployed_roles(groups)
        self.assertIn(STALWART, result)
        self.assertNotIn(MAILU, result)

    def test_none_and_empty_are_tolerated(self):
        self.assertEqual(deployed_roles(None), [])
        self.assertEqual(deployed_roles({}), [])

    def test_worker_resolves_the_same_provider_as_the_manager(self):
        groups = {STALWART: ["mgr-01"], "all": ["mgr-01", "wrk-01", "wrk-02"]}
        self.assertEqual(
            resolve_active_provider(STALWART, deployed_roles(groups), ROLES_DIR),
            STALWART,
            "a manager-pinned provider must still resolve on worker nodes",
        )

    def test_mailu_only_cluster_resolves_mailu_on_every_node(self):
        groups = {MAILU: ["mgr-01"], "all": ["mgr-01", "wrk-01"]}
        self.assertEqual(
            resolve_active_provider(STALWART, deployed_roles(groups), ROLES_DIR), MAILU
        )


if __name__ == "__main__":
    unittest.main()
