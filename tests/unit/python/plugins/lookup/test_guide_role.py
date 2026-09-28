import os
import unittest
from unittest.mock import patch

from plugins.lookup.guide_role import ENV_VAR, LookupModule, guide_role

INVOKABLE = ["web-app-docs", "web-app-nextcloud", "svc-db-postgres", "dsk-gnt-claude"]

NO_PIN = {ENV_VAR: ""}


class TestGuideRole(unittest.TestCase):
    def test_the_only_invokable_peer_wins(self):
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

    def test_one_of_the_peers_is_drawn(self):
        peers = ["svc-db-postgres", "dsk-gnt-claude"]
        self.assertIn(guide_role("web-app-docs", peers, INVOKABLE), peers)

    def test_every_peer_can_be_drawn(self):
        peers = ["svc-db-postgres", "dsk-gnt-claude"]
        drawn = {guide_role("web-app-docs", peers, INVOKABLE) for _ in range(200)}
        self.assertEqual(drawn, set(peers))

    def test_a_peer_outside_the_invokable_set_is_never_drawn(self):
        drawn = {
            guide_role(
                "web-app-docs",
                ["sys-svc-proxy", "user-administrator", "dsk-gnt-claude"],
                INVOKABLE,
            )
            for _ in range(200)
        }
        self.assertEqual(drawn, {"dsk-gnt-claude"})

    def test_the_pinned_role_outranks_the_draw(self):
        drawn = {
            guide_role(
                "web-app-docs",
                ["svc-db-postgres", "dsk-gnt-claude"],
                INVOKABLE,
                pinned="web-app-nextcloud",
            )
            for _ in range(200)
        }
        self.assertEqual(drawn, {"web-app-nextcloud"})

    def test_a_pin_without_a_guide_leaves_the_draw_alone(self):
        self.assertEqual(
            guide_role(
                "web-app-docs",
                ["web-app-nextcloud"],
                INVOKABLE,
                pinned="sys-svc-proxy",
            ),
            "web-app-nextcloud",
        )


class TestGuideRoleLookup(unittest.TestCase):
    @patch.dict(os.environ, NO_PIN)
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

    @patch.dict(os.environ, NO_PIN)
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

    @patch.dict(os.environ, NO_PIN)
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

    @patch.dict(os.environ, {ENV_VAR: "  dsk-gnt-claude  "})
    @patch("plugins.lookup.guide_role.list_invokable_app_ids")
    def test_the_environment_pins_the_role(self, invokable):
        invokable.return_value = INVOKABLE
        result = LookupModule().run(
            ["web-app-docs"],
            variables={"group_names": ["web-app-docs", "web-app-nextcloud"]},
        )
        self.assertEqual(result, ["dsk-gnt-claude"])


if __name__ == "__main__":
    unittest.main()
