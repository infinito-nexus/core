"""Unit tests for `cli.administration.deploy.development.inventory.planner`.

Covers ``plan_dev_inventory_matrix`` (mocking ``legacy_resolver``) and
``filter_plan_to_variants``.
"""

from __future__ import annotations

import unittest
from typing import ClassVar
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.inventory import (
    filter_plan_to_variants,
    plan_dev_inventory_matrix,
)


class TestPlanDevInventoryMatrix(unittest.TestCase):
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch(
        "cli.administration.deploy.development.inventory.planner.get_variants",
        autospec=True,
    )
    def test_single_variant_apps_share_one_unsuffixed_folder(
        self,
        get_variants_mock: MagicMock,
        _overrides_mock: MagicMock,
        resolve_include_mock: MagicMock,
    ) -> None:
        get_variants_mock.return_value = {
            "web-app-foo": [{}],
            "web-app-bar": [{}],
        }
        resolve_include_mock.return_value = ("web-app-foo", "web-app-bar")
        plan = plan_dev_inventory_matrix(
            roles_dir="/roles",
            primary_apps=["web-app-foo", "web-app-bar"],
            base_inventory_dir="/srv/inv",
        )
        self.assertEqual(
            plan,
            [
                (
                    0,
                    "/srv/inv",
                    {"web-app-foo": 0, "web-app-bar": 0},
                    ("web-app-foo", "web-app-bar"),
                    ("web-app-foo", "web-app-bar"),
                )
            ],
        )

    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch(
        "cli.administration.deploy.development.inventory.planner.get_variants",
        autospec=True,
    )
    def test_two_variant_primary_drives_two_suffixed_folders(
        self,
        get_variants_mock: MagicMock,
        _overrides_mock: MagicMock,
        resolve_include_mock: MagicMock,
    ) -> None:
        get_variants_mock.return_value = {
            "web-app-multi": [{"variant": 0}, {"variant": 1}],
            "web-app-keycloak": [{}],
        }
        resolve_include_mock.side_effect = [
            ("web-app-multi", "web-app-keycloak"),
            ("web-app-multi", "web-app-keycloak"),
        ]
        plan = plan_dev_inventory_matrix(
            roles_dir="/roles",
            primary_apps=["web-app-multi"],
            base_inventory_dir="/srv/inv",
        )
        self.assertEqual(
            plan,
            [
                (
                    0,
                    "/srv/inv-0",
                    {"web-app-multi": 0, "web-app-keycloak": 0},
                    ("web-app-multi", "web-app-keycloak"),
                    ("web-app-multi", "web-app-keycloak"),
                ),
                (
                    1,
                    "/srv/inv-1",
                    {"web-app-multi": 1, "web-app-keycloak": 0},
                    ("web-app-multi", "web-app-keycloak"),
                    ("web-app-multi", "web-app-keycloak"),
                ),
            ],
        )

    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch(
        "cli.administration.deploy.development.inventory.planner.get_variants",
        autospec=True,
    )
    def test_round_count_driven_by_primary_max_variants(
        self,
        get_variants_mock: MagicMock,
        _overrides_mock: MagicMock,
        resolve_include_mock: MagicMock,
    ) -> None:
        # Both primaries; rounds = max(3, 2) = 3.
        get_variants_mock.return_value = {
            "web-app-three": [{}, {}, {}],
            "web-app-two": [{}, {}],
        }
        resolve_include_mock.side_effect = [
            ("web-app-three", "web-app-two"),
            ("web-app-three", "web-app-two"),
            ("web-app-three", "web-app-two"),
        ]
        plan = plan_dev_inventory_matrix(
            roles_dir="/roles",
            primary_apps=["web-app-three", "web-app-two"],
            base_inventory_dir="/srv/inv",
        )
        # Round 0,1,2 -> three has 0,1,2 / two has 0,1,0 (clamped on R=2).
        self.assertEqual(
            plan,
            [
                (
                    0,
                    "/srv/inv-0",
                    {"web-app-three": 0, "web-app-two": 0},
                    ("web-app-three", "web-app-two"),
                    ("web-app-three", "web-app-two"),
                ),
                (
                    1,
                    "/srv/inv-1",
                    {"web-app-three": 1, "web-app-two": 1},
                    ("web-app-three", "web-app-two"),
                    ("web-app-three", "web-app-two"),
                ),
                (
                    2,
                    "/srv/inv-2",
                    {"web-app-three": 2, "web-app-two": 0},
                    ("web-app-three", "web-app-two"),
                    ("web-app-three", "web-app-two"),
                ),
            ],
        )

    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch(
        "cli.administration.deploy.development.inventory.planner.get_variants",
        autospec=True,
    )
    def test_purge_set_is_union_when_variants_differ(
        self,
        get_variants_mock: MagicMock,
        _overrides_mock: MagicMock,
        resolve_include_mock: MagicMock,
    ) -> None:
        # WHY: per-round include must stay variant-specific while purge_set must be the union, otherwise the inter-round wipe leaks coturn into round 1.
        get_variants_mock.return_value = {
            "web-app-nextcloud": [{"shared_coturn": True}, {"shared_coturn": False}],
        }
        resolve_include_mock.side_effect = [
            ("web-app-nextcloud", "web-svc-coturn"),
            ("web-app-nextcloud",),
        ]
        plan = plan_dev_inventory_matrix(
            roles_dir="/roles",
            primary_apps=["web-app-nextcloud"],
            base_inventory_dir="/srv/inv",
        )
        self.assertEqual(plan[0][3], ("web-app-nextcloud", "web-svc-coturn"))
        self.assertEqual(plan[1][3], ("web-app-nextcloud",))
        union = ("web-app-nextcloud", "web-svc-coturn")
        self.assertEqual(plan[0][4], union)
        self.assertEqual(plan[1][4], union)

    def test_empty_primary_apps_rejected(self):
        with self.assertRaises(ValueError):
            plan_dev_inventory_matrix(
                roles_dir="/roles",
                primary_apps=[],
                base_inventory_dir="/srv/inv",
            )


class TestFilterPlanToVariants(unittest.TestCase):
    PLAN: ClassVar[list[tuple]] = [
        (i, f"/srv/inv-{i}", {"web-app-multi": i}, ("web-app-multi",), ())
        for i in range(5)
    ]

    def test_none_returns_full_plan(self):
        self.assertEqual(filter_plan_to_variants(self.PLAN, None), self.PLAN)

    def test_subset_keeps_only_listed_rounds_in_plan_order(self):
        self.assertEqual(
            filter_plan_to_variants(self.PLAN, [0, 1, 2]),
            self.PLAN[:3],
        )
        self.assertEqual(
            filter_plan_to_variants(self.PLAN, [3, 4]),
            self.PLAN[3:],
        )

    def test_order_follows_plan_not_argument(self):
        self.assertEqual(
            filter_plan_to_variants(self.PLAN, [4, 0]),
            [self.PLAN[0], self.PLAN[4]],
        )

    def test_out_of_range_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, r"variants \[7\] out of range"):
            filter_plan_to_variants(self.PLAN, [0, 7])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
