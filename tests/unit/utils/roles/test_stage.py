"""Stage resolution reads roles/categories.yml as the SPOT: the ordered
`stages` list, the per-category `stage`, and the run_after tiebreak that
places roles in constructor -> workstation -> server -> destructor order."""

from __future__ import annotations

import unittest

from utils.roles.stage import role_sort_key, role_stage, stage_groups, stage_order


class TestStage(unittest.TestCase):
    def test_stage_order_is_the_four_stages(self) -> None:
        self.assertEqual(
            stage_order(), ["constructor", "workstation", "server", "destructor"]
        )

    def test_role_stage_by_category(self) -> None:
        self.assertEqual(role_stage("web-app-nextcloud"), "server")
        self.assertEqual(role_stage("desk-gnome"), "workstation")
        self.assertEqual(role_stage("update-pacman"), "constructor")

    def test_deepest_category_wins(self) -> None:
        self.assertEqual(role_stage("svc-db-postgres"), "constructor")
        self.assertEqual(role_stage("svc-opt-ssd-hdd"), "destructor")

    def test_unknown_role_defaults_to_server(self) -> None:
        self.assertEqual(role_stage("totally-unknown-role"), "server")

    def test_sort_key_orders_by_stage_then_category_then_name(self) -> None:
        keys = [
            role_sort_key(r)
            for r in ["svc-opt-ssd-hdd", "web-app-a", "web-svc-html", "desk-gnome"]
        ]
        self.assertEqual(
            [
                r
                for _, r in sorted(
                    zip(keys, ["svc-opt", "web-app", "web-svc", "desk"], strict=True)
                )
            ],
            ["desk", "web-svc", "web-app", "svc-opt"],
        )

    def test_stage_groups_match_wired_stage_loops(self) -> None:
        """The lookup must reproduce the exact group order the stage plays used
        to hardcode, so wiring them onto the SPOT changes no behavior."""
        self.assertEqual(
            stage_groups("constructor"),
            [
                "update",
                "drv",
                "gen",
                "svc-net",
                "svc-db",
                "svc-dns",
                "svc-prx",
                "svc-ai",
                "svc-bkp",
                "svc-runner",
            ],
        )
        self.assertEqual(stage_groups("server"), ["web-svc", "web-app", "web-opt"])
        self.assertEqual(stage_groups("workstation"), ["desk"])
        self.assertEqual(stage_groups("destructor"), ["svc-opt"])

    def test_bootstrap_groups_excluded_from_stage_groups(self) -> None:
        """storage/registry/swarm are bootstrapped by dedicated steps, so they
        must never leak into the generic constructor group-loop."""
        for group in ("svc-storage", "svc-registry", "svc-swarm"):
            self.assertNotIn(group, stage_groups("constructor"))


if __name__ == "__main__":
    unittest.main()
