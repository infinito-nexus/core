from __future__ import annotations

import unittest

from plugins.lookup.agent_config import LookupModule
from utils import PROJECT_ROOT
from utils.agents.accounts import (
    available_accounts,
    default_account,
    repository_accounts,
    repository_entry,
    worked_through,
)
from utils.cache.yaml import load_yaml
from utils.firewall.compile import account_grants

FIREWALL_ROLES = load_yaml(PROJECT_ROOT / "agents" / "firewall" / "roles.yml")
GITHUB = "github/maintainer"
GITEA = "gitea/maintainer"


def _agent(path: str, override: dict):
    variables = {"agents": {"maintainer": override}}
    return LookupModule().run(["maintainer", path], variables=variables)[0]


def _scope(override: dict) -> list[dict]:
    grants = account_grants(FIREWALL_ROLES, _agent("firewall_roles", override))
    available = available_accounts(_agent("credentials", override), set())
    return repository_accounts(_agent("repositories", override), grants, available)


class TestAvailableAccounts(unittest.TestCase):
    def test_the_shipped_maintainer_grants_github_first(self):
        self.assertEqual(
            account_grants(FIREWALL_ROLES, ["maintainer"]),
            [GITHUB, GITEA, "gitlab/maintainer"],
        )

    def test_a_github_grant_without_credentials_is_inactive(self):
        grants = account_grants(FIREWALL_ROLES, ["maintainer"])
        available = available_accounts({GITHUB: {}, GITEA: {"token": "t"}}, set())
        self.assertEqual(available, {GITEA})
        self.assertEqual(default_account(grants, available), GITEA)

    def test_github_credentials_make_github_the_default(self):
        grants = account_grants(FIREWALL_ROLES, ["maintainer"])
        available = available_accounts(
            {GITHUB: {"token": "t"}, GITEA: {"token": "u"}}, set()
        )
        self.assertEqual(default_account(grants, available), GITHUB)

    def test_a_provisioned_account_is_active_without_inventory_credentials(self):
        grants = account_grants(FIREWALL_ROLES, ["maintainer"])
        available = available_accounts({}, {"gitlab/maintainer"})
        self.assertEqual(default_account(grants, available), "gitlab/maintainer")

    def test_inventory_credentials_reach_the_selection_through_the_lookup(self):
        override = {"credentials": {GITEA: {"token": "t"}}}
        available = available_accounts(_agent("credentials", override), set())
        grants = account_grants(FIREWALL_ROLES, _agent("firewall_roles", override))
        self.assertEqual(default_account(grants, available), GITEA)
        self.assertIsNone(
            default_account(
                grants, available_accounts(_agent("credentials", {}), set())
            )
        )


class TestRepositoryEntries(unittest.TestCase):
    def test_an_entry_without_an_account(self):
        self.assertEqual(
            repository_entry("infinito-nexus/core"),
            {"repo": "infinito-nexus/core", "account": None},
        )

    def test_an_entry_naming_an_account(self):
        self.assertEqual(
            repository_entry("gitea/maintainer:infinito-nexus/core"),
            {"repo": "infinito-nexus/core", "account": GITEA},
        )

    def test_malformed_entries_are_refused(self):
        for bad in ("core", "gitea:infinito-nexus/core", "a/b/c", "x/y:", ""):
            with self.subTest(entry=bad), self.assertRaises(ValueError):
                repository_entry(bad)

    def test_dot_segments_and_a_trailing_newline_are_refused(self):
        for bad in (
            "owner/..",
            "../core",
            "./core",
            "owner/.",
            ".../x",
            "infinito-nexus/core\n",
            "github/..:infinito-nexus/core",
            "github/maintainer\n:infinito-nexus/core",
        ):
            with self.subTest(entry=bad), self.assertRaises(ValueError):
                repository_entry(bad)

    def test_a_dotted_name_that_is_not_all_dots_is_kept(self):
        self.assertEqual(
            repository_entry("infinito-nexus/.github"),
            {"repo": "infinito-nexus/.github", "account": None},
        )


class TestRepositoryAccounts(unittest.TestCase):
    GRANTS = (GITHUB, GITEA)

    def test_a_named_account_is_used_instead_of_the_default(self):
        scope = repository_accounts(
            ["gitea/maintainer:acme/widgets", "infinito-nexus/core"],
            list(self.GRANTS),
            {GITHUB, GITEA},
        )
        self.assertEqual(worked_through(scope, "acme/widgets"), GITEA)
        self.assertEqual(worked_through(scope, "infinito-nexus/core"), GITHUB)

    def test_a_named_account_without_credentials_never_falls_back(self):
        scope = repository_accounts(
            ["gitea/maintainer:acme/widgets"], list(self.GRANTS), {GITHUB}
        )
        with self.assertRaisesRegex(PermissionError, "no credentials"):
            worked_through(scope, "acme/widgets")

    def test_a_named_account_outside_the_grants_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no account grant"):
            repository_accounts(
                ["gitlab/maintainer:acme/widgets"], list(self.GRANTS), {GITHUB}
            )


class TestInventoryRepositories(unittest.TestCase):
    def test_the_shipped_list_works_on_core_through_the_default(self):
        scope = _scope({"credentials": {GITHUB: {"token": "t"}}})
        self.assertEqual(worked_through(scope, "infinito-nexus/core"), GITHUB)

    def test_an_inventory_list_restricts_the_agent_to_its_repositories(self):
        scope = _scope(
            {
                "repositories": ["gitea/maintainer:acme/widgets"],
                "credentials": {GITHUB: {"token": "t"}, GITEA: {"token": "u"}},
            }
        )
        self.assertEqual(worked_through(scope, "acme/widgets"), GITEA)
        with self.assertRaisesRegex(PermissionError, "not in the agent's repositories"):
            worked_through(scope, "infinito-nexus/core")


if __name__ == "__main__":
    unittest.main()
