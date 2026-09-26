import unittest
from unittest.mock import patch

from plugins.lookup.guide_role import LookupModule, guide_role

INVOKABLE = ["web-app-docs", "web-app-nextcloud", "svc-db-postgres", "dsk-gnt-claude"]


class TestGuideRole(unittest.TestCase):
    def test_the_first_invokable_peer_wins(self):
        self.assertEqual(
            guide_role(
                "web-app-docs", ["web-app-docs", "web-app-nextcloud"], INVOKABLE
            ),
            "web-app-nextcloud",
        )

    def test_a_non_invokable_peer_is_no_peer(self):
        self.assertEqual(
            guide_role("web-app-docs", ["web-app-docs", "sys-svc-proxy"], INVOKABLE),
            "web-app-docs",
        )

    def test_the_asking_role_alone_names_itself(self):
        self.assertEqual(
            guide_role("web-app-docs", ["web-app-docs"], INVOKABLE), "web-app-docs"
        )

    def test_an_empty_round_names_the_asking_role(self):
        self.assertEqual(guide_role("web-app-docs", [], INVOKABLE), "web-app-docs")

    def test_the_round_order_decides_between_two_peers(self):
        self.assertEqual(
            guide_role(
                "web-app-docs", ["svc-db-postgres", "dsk-gnt-claude"], INVOKABLE
            ),
            "svc-db-postgres",
        )

    def test_a_peer_outside_the_invokable_set_is_skipped_for_a_later_one(self):
        self.assertEqual(
            guide_role(
                "web-app-docs",
                ["sys-svc-proxy", "user-administrator", "dsk-gnt-claude"],
                INVOKABLE,
            ),
            "dsk-gnt-claude",
        )


class TestGuideRoleLookup(unittest.TestCase):
    @patch("plugins.lookup.guide_role.list_invokable_app_ids")
    def test_the_whitelist_outranks_the_round_groups(self, invokable):
        invokable.return_value = INVOKABLE
        result = LookupModule().run(
            ["web-app-docs"],
            variables={
                "APPLICATIONS_WHITELIST": ["web-app-docs", "svc-db-postgres"],
                "group_names": ["web-app-docs", "web-app-nextcloud"],
            },
        )
        self.assertEqual(result, ["svc-db-postgres"])

    @patch("plugins.lookup.guide_role.list_invokable_app_ids")
    def test_without_a_whitelist_the_round_groups_decide(self, invokable):
        invokable.return_value = INVOKABLE
        result = LookupModule().run(
            ["web-app-docs"],
            variables={
                "APPLICATIONS_WHITELIST": [],
                "group_names": ["web-app-docs", "web-app-nextcloud"],
            },
        )
        self.assertEqual(result, ["web-app-nextcloud"])

    @patch("plugins.lookup.guide_role.list_invokable_app_ids")
    def test_the_asking_role_falls_back_to_the_variable(self, invokable):
        invokable.return_value = INVOKABLE
        result = LookupModule().run(
            [],
            variables={
                "application_id": "web-app-docs",
                "group_names": ["web-app-docs", "sys-svc-proxy"],
            },
        )
        self.assertEqual(result, ["web-app-docs"])


if __name__ == "__main__":
    unittest.main()
