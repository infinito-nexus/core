"""Unit tests for `cli.administration.deploy.development.inventory.builder`."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cli.administration.deploy.development.common import DEV_INVENTORY_VARS_FILE
from cli.administration.deploy.development.inventory import (
    build_dev_inventory,
    build_dev_inventory_matrix,
)

from ._fixtures import make_spec


class TestBuildDevInventory(unittest.TestCase):
    def setUp(self) -> None:
        self.compose = MagicMock()
        # Used by inventory.payload to locate roles_dir for variant lookup.
        self.compose.repo_root = Path("/tmp/infinito-nexus")

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={
            "web-app-keycloak": [{}],
            "web-app-nextcloud": [{}],
        },
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_invokes_infinito_inventory_provision_with_spot_vars_file(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, make_spec())

        # First exec call is the `infinito administration inventory provision ...`
        # cmd; the second is the password-file ensure step.
        self.assertEqual(self.compose.exec.call_count, 2)
        first_cmd = self.compose.exec.call_args_list[0].args[0]
        self.assertEqual(
            first_cmd[0:4],
            ["infinito", "administration", "inventory", "provision"],
        )
        # SPOT enforcement: the vars-file MUST come from the common.py constant.
        vars_file_index = first_cmd.index("--vars-file") + 1
        self.assertEqual(first_cmd[vars_file_index], DEV_INVENTORY_VARS_FILE)

        include_index = first_cmd.index("--include") + 1
        self.assertEqual(first_cmd[include_index], "web-app-keycloak,web-app-nextcloud")

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={
            "web-app-multi": [
                {"server": {"domains": {"canonical": ["multi.example"]}}},
                {
                    "server": {
                        "domains": {"canonical": ["blog.multi.example"]},
                    },
                    # Per: services live at applications.<app>.services
                    # directly (no `compose.services` envelope).
                    "services": {"x": {"flag": True}},
                },
            ],
        },
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_active_variant_one_is_baked_into_applications_overrides(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        spec = make_spec(
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
        "cli.administration.deploy.development.inventory.builder.generate_ci_mirrors_file",
        autospec=True,
        return_value="/etc/mirrors.yml",
    )
    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=True,
    )
    def test_appends_mirror_arg_on_ci(
        self,
        _mirrors_active_mock: MagicMock,
        _variants_mock: MagicMock,
        mirrors_file_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, make_spec())

        first_cmd = self.compose.exec.call_args_list[0].args[0]
        mirror_index = first_cmd.index("--mirror") + 1
        self.assertEqual(first_cmd[mirror_index], "/etc/mirrors.yml")
        mirrors_file_mock.assert_called_once_with(
            self.compose, inventory_dir="/tmp/inv"
        )

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_propagates_services_disabled_into_extra_env(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(
            self.compose, make_spec(services_disabled="svc-foo,svc-bar")
        )

        first_kwargs = self.compose.exec.call_args_list[0].kwargs
        self.assertEqual(
            first_kwargs.get("extra_env"),
            {"disable": "svc-foo,svc-bar"},
        )

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_omits_extra_env_when_services_disabled_unset(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, make_spec())

        first_kwargs = self.compose.exec.call_args_list[0].kwargs
        self.assertIsNone(first_kwargs.get("extra_env"))

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={
            "svc-bkp-container-2-local": [{}, {}, {}],
        },
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_passes_app_variants_when_round_pins_variants(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        spec = make_spec(
            include=("svc-bkp-container-2-local",),
            active_variants={"svc-bkp-container-2-local": 2},
        )
        build_dev_inventory(self.compose, spec)

        first_cmd = self.compose.exec.call_args_list[0].args[0]
        self.assertIn("--app-variants", first_cmd)
        variants_index = first_cmd.index("--app-variants") + 1
        self.assertEqual(
            json.loads(first_cmd[variants_index]),
            {"svc-bkp-container-2-local": 2},
        )

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_omits_app_variants_when_round_has_none(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, make_spec())
        first_cmd = self.compose.exec.call_args_list[0].args[0]
        self.assertNotIn("--app-variants", first_cmd)

    @patch(
        "cli.administration.deploy.development.inventory.payload.get_variant_overrides_only",
        autospec=True,
        return_value={"web-app-keycloak": [{}], "web-app-nextcloud": [{}]},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.should_use_mirrors_on_ci",
        autospec=True,
        return_value=False,
    )
    def test_runs_password_file_ensure_step(
        self,
        _mirrors_mock: MagicMock,
        _variants_mock: MagicMock,
    ) -> None:
        build_dev_inventory(self.compose, make_spec(inventory_dir="/srv/inv/"))

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
        "cli.administration.deploy.development.inventory.legacy_resolver._resolve_round_include",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.legacy_resolver._build_services_overrides_for_round",
        autospec=True,
        return_value={},
    )
    @patch(
        "cli.administration.deploy.development.inventory.builder.build_dev_inventory",
        autospec=True,
    )
    @patch(
        "cli.administration.deploy.development.inventory.planner.get_variants",
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
            [(idx, inv, vs, inc, purge) for idx, inv, vs, inc, purge in plan],
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
        # One build_dev_inventory call per round; each gets a spec whose
        # active_variants matches the round's plan entry and whose include
        # is the round's variant-resolved include set.
        self.assertEqual(build_inventory_mock.call_count, 2)
        for (_round_idx, inv_dir, round_vars, round_include, _purge), call in zip(
            plan, build_inventory_mock.call_args_list, strict=False
        ):
            spec_arg = call.args[1]
            self.assertEqual(spec_arg.inventory_dir, inv_dir)
            self.assertEqual(dict(spec_arg.active_variants or {}), round_vars)
            self.assertEqual(tuple(spec_arg.include), round_include)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
