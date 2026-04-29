"""Unit tests for the development inventory build SPOT
(`cli.deploy.development.inventory`)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.deploy.development.common import DEV_INVENTORY_VARS_FILE
from cli.deploy.development.inventory import (
    DevInventorySpec,
    _bake_overrides,
    _resolve_variant_payloads,
    build_dev_inventory,
    build_dev_inventory_matrix,
    filter_plan_to_variant,
    plan_dev_inventory_matrix,
)


def _spec(**overrides) -> DevInventorySpec:
    base = dict(
        inventory_dir="/tmp/inv",
        include=("web-app-keycloak", "web-app-nextcloud"),
        storage_constrained=False,
        runtime="dev",
    )
    base.update(overrides)
    return DevInventorySpec(**base)


class TestDevInventorySpec(unittest.TestCase):
    def test_empty_include_rejected(self):
        with self.assertRaises(ValueError):
            DevInventorySpec(
                inventory_dir="/tmp/inv",
                include=(),
                storage_constrained=False,
                runtime="dev",
            )

    def test_list_include_normalised_to_tuple(self):
        spec = DevInventorySpec(
            inventory_dir="/tmp/inv",
            include=["web-app-keycloak"],
            storage_constrained=True,
            runtime="dev",
        )
        self.assertIsInstance(spec.include, tuple)
        self.assertEqual(spec.include, ("web-app-keycloak",))

    def test_overrides_default(self):
        spec = _spec(storage_constrained=True, runtime="prod")
        self.assertEqual(
            spec.overrides(),
            {"STORAGE_CONSTRAINED": True, "RUNTIME": "prod"},
        )

    def test_extra_vars_win_over_implicit_overrides(self):
        spec = _spec(
            storage_constrained=False,
            runtime="dev",
            extra_vars={"STORAGE_CONSTRAINED": True, "FOO": "bar"},
        )
        self.assertEqual(
            spec.overrides(),
            {"STORAGE_CONSTRAINED": True, "RUNTIME": "dev", "FOO": "bar"},
        )

    def test_inventory_root_strips_trailing_slash(self):
        spec = _spec(inventory_dir="/tmp/inv///")
        self.assertEqual(spec.inventory_root(), "/tmp/inv")

    def test_variant_selectors_default_to_empty_dict(self):
        self.assertEqual(_spec().variant_selectors(), {})

    def test_variant_selectors_returned_as_plain_dict(self):
        spec = _spec(active_variants={"web-app-keycloak": 2})
        self.assertEqual(spec.variant_selectors(), {"web-app-keycloak": 2})


class TestResolveVariantPayloads(unittest.TestCase):
    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
    def test_app_without_meta_collapses_to_variant_zero_payload(
        self, get_variants_mock: MagicMock
    ) -> None:
        # No `meta/variants.yml` -> loader exposes a single empty variant,
        # i.e. `[{}]`. The 1st entry MUST be picked even though no variant
        # was authored, so the per-app bake stays uniform.
        get_variants_mock.return_value = {"web-app-foo": [{}]}

        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-foo"],
            active_variants={},
        )
        self.assertEqual(resolved, {"web-app-foo": {}})

    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
    def test_active_variants_picks_named_variant(
        self, get_variants_mock: MagicMock
    ) -> None:
        get_variants_mock.return_value = {
            "web-app-multi": [{"variant": 0}, {"variant": 1}],
        }
        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-multi"],
            active_variants={"web-app-multi": 1},
        )
        self.assertEqual(resolved, {"web-app-multi": {"variant": 1}})

    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
    def test_out_of_range_index_falls_back_to_variant_zero(
        self, get_variants_mock: MagicMock
    ) -> None:
        get_variants_mock.return_value = {
            "web-app-multi": [{"variant": 0}, {"variant": 1}],
        }
        resolved = _resolve_variant_payloads(
            roles_dir="/roles",
            include=["web-app-multi"],
            active_variants={"web-app-multi": 99},
        )
        self.assertEqual(resolved, {"web-app-multi": {"variant": 0}})


class TestBakeOverrides(unittest.TestCase):
    def test_user_supplied_applications_override_wins_over_variant_payload(self):
        baked = _bake_overrides(
            base_overrides={
                "STORAGE_CONSTRAINED": False,
                "RUNTIME": "dev",
                "applications": {
                    "web-app-foo": {"feature_flag": True},
                },
            },
            variant_payloads={
                "web-app-foo": {"feature_flag": False, "image": "v1"},
            },
        )
        # User override wins on conflicting keys; non-conflicting keys
        # from the variant payload remain visible.
        self.assertEqual(
            baked["applications"]["web-app-foo"],
            {"feature_flag": True, "image": "v1"},
        )

    def test_no_variant_payloads_yields_unchanged_base(self):
        base = {"STORAGE_CONSTRAINED": False, "RUNTIME": "dev"}
        baked = _bake_overrides(base_overrides=base, variant_payloads={})
        self.assertEqual(baked, base)


class TestPlanDevInventoryMatrix(unittest.TestCase):
    @patch(
        "cli.deploy.development.inventory._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.deploy.development.inventory._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
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
                )
            ],
        )

    @patch(
        "cli.deploy.development.inventory._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.deploy.development.inventory._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
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
                ),
                (
                    1,
                    "/srv/inv-1",
                    {"web-app-multi": 1, "web-app-keycloak": 0},
                    ("web-app-multi", "web-app-keycloak"),
                ),
            ],
        )

    @patch(
        "cli.deploy.development.inventory._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.deploy.development.inventory._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch("cli.deploy.development.inventory.get_variants", autospec=True)
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
                ),
                (
                    1,
                    "/srv/inv-1",
                    {"web-app-three": 1, "web-app-two": 1},
                    ("web-app-three", "web-app-two"),
                ),
                (
                    2,
                    "/srv/inv-2",
                    {"web-app-three": 2, "web-app-two": 0},
                    ("web-app-three", "web-app-two"),
                ),
            ],
        )

    def test_empty_primary_apps_rejected(self):
        with self.assertRaises(ValueError):
            plan_dev_inventory_matrix(
                roles_dir="/roles",
                primary_apps=[],
                base_inventory_dir="/srv/inv",
            )


class TestFilterPlanToVariant(unittest.TestCase):
    PLAN = [
        (
            0,
            "/srv/inv-0",
            {"web-app-multi": 0, "web-app-keycloak": 0},
            ("web-app-multi", "web-app-keycloak"),
        ),
        (
            1,
            "/srv/inv-1",
            {"web-app-multi": 1, "web-app-keycloak": 0},
            ("web-app-multi", "web-app-keycloak"),
        ),
    ]

    def test_none_returns_full_plan(self):
        self.assertEqual(filter_plan_to_variant(self.PLAN, None), self.PLAN)

    def test_pins_to_named_round(self):
        self.assertEqual(
            filter_plan_to_variant(self.PLAN, 1),
            [self.PLAN[1]],
        )

    def test_out_of_range_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "variant 7 out of range"):
            filter_plan_to_variant(self.PLAN, 7)


class TestBuildDevInventory(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = MagicMock()
        # Used by inventory.py to locate roles_dir for variant lookup.
        self.compose.repo_root = Path("/tmp/infinito-nexus")

    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={
            "web-app-keycloak": [{}],
            "web-app-nextcloud": [{}],
        },
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_invokes_infinito_create_inventory_with_spot_vars_file(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, _spec())

        # First exec call is the `infinito create inventory ...` cmd; the
        # second is the password-file ensure step.
        self.assertEqual(self.compose.exec.call_count, 2)
        first_cmd = self.compose.exec.call_args_list[0].args[0]
        self.assertEqual(first_cmd[0:3], ["infinito", "create", "inventory"])
        # SPOT enforcement: the vars-file MUST come from the common.py constant.
        vars_file_index = first_cmd.index("--vars-file") + 1
        self.assertEqual(first_cmd[vars_file_index], DEV_INVENTORY_VARS_FILE)

        include_index = first_cmd.index("--include") + 1
        self.assertEqual(first_cmd[include_index], "web-app-keycloak,web-app-nextcloud")

    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={
            "web-app-multi": [
                {"server": {"domains": {"canonical": ["multi.example"]}}},
                {
                    "server": {
                        "domains": {"canonical": ["blog.multi.example"]},
                    },
                    # Per req-008: services live at applications.<app>.services
                    # directly (no `compose.services` envelope).
                    "services": {"x": {"flag": True}},
                },
            ],
        },
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_active_variant_one_is_baked_into_applications_overrides(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        spec = _spec(
            include=("web-app-multi",),
            active_variants={"web-app-multi": 1},
        )
        build_dev_inventory(self.compose, spec)

        first_cmd = self.compose.exec.call_args_list[0].args[0]
        vars_index = first_cmd.index("--vars") + 1
        baked = json.loads(first_cmd[vars_index])

        self.assertEqual(
            baked["applications"]["web-app-multi"]["server"]["domains"]["canonical"],
            ["blog.multi.example"],
        )
        self.assertEqual(
            baked["applications"]["web-app-multi"]["services"]["x"],
            {"flag": True},
        )
        # Implicit overrides untouched:
        self.assertEqual(baked["STORAGE_CONSTRAINED"], False)
        self.assertEqual(baked["RUNTIME"], "dev")

    @patch(
        "cli.deploy.development.inventory.generate_ci_mirrors_file",
        autospec=True,
        return_value="/etc/mirrors.yml",
    )
    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=True,
    )
    def test_appends_mirror_arg_on_ci(
        self,
        _mirrors_active_mock: MagicMock,
        _variants_mock: MagicMock,
        mirrors_file_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, _spec())

        first_cmd = self.compose.exec.call_args_list[0].args[0]
        mirror_index = first_cmd.index("--mirror") + 1
        self.assertEqual(first_cmd[mirror_index], "/etc/mirrors.yml")
        mirrors_file_mock.assert_called_once_with(
            self.compose, inventory_dir="/tmp/inv"
        )

    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_propagates_services_disabled_into_extra_env(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, _spec(services_disabled="svc-foo,svc-bar"))

        first_kwargs = self.compose.exec.call_args_list[0].kwargs
        self.assertEqual(
            first_kwargs.get("extra_env"),
            {"SERVICES_DISABLED": "svc-foo,svc-bar"},
        )

    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_omits_extra_env_when_services_disabled_unset(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, _spec())

        first_kwargs = self.compose.exec.call_args_list[0].kwargs
        self.assertIsNone(first_kwargs.get("extra_env"))

    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.deploy.development.inventory.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_runs_password_file_ensure_step(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, _spec(inventory_dir="/srv/inv/"))

        password_cmd = self.compose.exec.call_args_list[1].args[0]
        self.assertEqual(password_cmd[0], "sh")
        self.assertEqual(password_cmd[1], "-lc")
        shell_script = password_cmd[2]
        self.assertIn("mkdir -p /srv/inv", shell_script)
        self.assertIn("/srv/inv/.password", shell_script)


class TestBuildDevInventoryMatrix(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = MagicMock()
        self.compose.repo_root = Path("/tmp/infinito-nexus")

    @patch(
        "cli.deploy.development.inventory._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.deploy.development.inventory._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch("cli.deploy.development.inventory.build_dev_inventory", autospec=True)
    @patch(
        "cli.deploy.development.inventory.get_variants",
        autospec=True,
        return_value={
            "web-app-multi": [{"v": 0}, {"v": 1}],
            "web-app-keycloak": [{}],
        },
    )
    def test_builds_one_inventory_per_round_and_returns_plan(
        self,
        _variants_mock: MagicMock,
        build_inventory_mock: MagicMock,
        _overrides_mock: MagicMock,
        resolve_include_mock: MagicMock,
    ) -> None:
        resolve_include_mock.side_effect = [
            ("web-app-multi", "web-app-keycloak"),
            ("web-app-multi", "web-app-keycloak"),
        ]
        plan = build_dev_inventory_matrix(
            self.compose,
            base_inventory_dir="/srv/inv",
            primary_apps=("web-app-multi",),
            storage_constrained=False,
            runtime="dev",
        )

        self.assertEqual(
            [(idx, inv, vs, inc) for idx, inv, vs, inc in plan],
            [
                (
                    0,
                    "/srv/inv-0",
                    {"web-app-multi": 0, "web-app-keycloak": 0},
                    ("web-app-multi", "web-app-keycloak"),
                ),
                (
                    1,
                    "/srv/inv-1",
                    {"web-app-multi": 1, "web-app-keycloak": 0},
                    ("web-app-multi", "web-app-keycloak"),
                ),
            ],
        )
        # One build_dev_inventory call per round; each gets a spec whose
        # active_variants matches the round's plan entry and whose include
        # is the round's variant-resolved include set.
        self.assertEqual(build_inventory_mock.call_count, 2)
        for (round_idx, inv_dir, round_vars, include_R), call in zip(
            plan, build_inventory_mock.call_args_list
        ):
            spec_arg = call.args[1]
            self.assertEqual(spec_arg.inventory_dir, inv_dir)
            self.assertEqual(dict(spec_arg.active_variants or {}), round_vars)
            self.assertEqual(tuple(spec_arg.include), include_R)


if __name__ == "__main__":
    unittest.main()
