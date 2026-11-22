from __future__ import annotations

import io
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

from cli.meta.ci import validate
from utils.github.variant import axes, network

_ROWS = [
    {"name": "web-app-a", "variant": 0, "test_compose": True, "test_swarm": True},
    {"name": "web-app-a", "variant": 1, "test_compose": True, "test_swarm": False},
    {"name": "web-app-b", "variant": 0, "test_compose": False, "test_swarm": True},
]

_VARIANTS = {
    "web-app-a": [
        {"services": {"tor": {"enabled": True}}},
        {"services": {"tor": {"enabled": False}}},
    ],
    "web-app-b": [
        {
            "services": {"tor": {"enabled": True}},
            "networks": {"reachability": {"single_mode": True}},
        }
    ],
}

_NOTHING_DEPLOYED = ((), ())


def _problems(
    tokens: str,
    *,
    network_input: str = "auto",
    vpn_mode: str = "auto",
    whitelist: bool = False,
) -> tuple[list[str], list[str]]:
    with (
        mock.patch.object(validate.query, "discover_rows", return_value=_ROWS),
        mock.patch.object(validate, "get_variants", return_value=_VARIANTS),
        mock.patch.object(
            validate.matrix, "deployed_rounds", return_value=_NOTHING_DEPLOYED
        ),
    ):
        return validate.problems(
            tokens,
            modes=("compose", "swarm", "host"),
            network_input=network_input,
            vpn_mode=vpn_mode,
            distros=axes.DISTROS,
            filesystems=axes.FILESYSTEMS,
            lifecycles="",
            label="whitelist" if whitelist else "priority",
            priority=not whitelist,
        )


_NOTHING_LEFT = "leaves no (mode, network, mesh) combination"


class TestProblems(unittest.TestCase):
    def test_nothing_to_check_is_not_a_problem(self) -> None:
        self.assertEqual(_problems(""), ([], []))

    def test_a_token_the_branch_can_deploy_passes(self) -> None:
        self.assertEqual(_problems("web-app-a#0@swarm+tor"), ([], []))

    def test_a_variant_the_role_no_longer_declares_is_an_error(self) -> None:
        errors, warnings = _problems("web-app-a#7@compose+tor")
        self.assertEqual(warnings, [])
        self.assertIn("matches no discovered row", errors[0])
        self.assertIn("2 variant(s)", errors[0])

    def test_a_bare_role_that_matches_nothing_only_warns(self) -> None:
        errors, warnings = _problems("web-app-gone")
        self.assertEqual(errors, [])
        self.assertIn("web-app-gone", warnings[0])

    def test_a_pinned_role_the_run_never_discovers_only_warns(self) -> None:
        errors, warnings = _problems("web-app-gone#0,2")
        self.assertEqual(errors, [])
        self.assertIn("web-app-gone", warnings[0])

    def test_a_bare_role_the_run_discovers_is_silent(self) -> None:
        self.assertEqual(_problems("web-app-a"), ([], []))

    def test_a_bare_role_is_judged_on_existence_not_on_variant_zero(self) -> None:
        rows = [{"name": "web-app-c", "variant": 4, "test_compose": True}]
        with (
            mock.patch.object(validate.query, "discover_rows", return_value=rows),
            mock.patch.object(
                validate, "get_variants", return_value={"web-app-c": [{"services": {}}]}
            ),
            mock.patch.object(
                validate.matrix, "deployed_rounds", return_value=_NOTHING_DEPLOYED
            ),
        ):
            errors, warnings = validate.problems(
                "web-app-c",
                modes=("compose",),
                network_input="auto",
                vpn_mode="auto",
                distros=axes.DISTROS,
                filesystems=axes.FILESYSTEMS,
                lifecycles="",
                label="priority",
            )
        self.assertEqual((errors, warnings), ([], []))

    def _bondless_multi(
        self, listed: list[str], deployed: tuple[str, ...]
    ) -> tuple[list[str], list[str]]:
        rows = [
            {
                "name": "web-app-c",
                "variant": 0,
                "test_compose": True,
                "services": listed,
            }
        ]
        with (
            mock.patch.object(validate.query, "discover_rows", return_value=rows),
            mock.patch.object(
                validate, "get_variants", return_value={"web-app-c": [{"services": {}}]}
            ),
            mock.patch.object(
                validate.matrix, "deployed_rounds", return_value=(deployed,)
            ),
        ):
            return validate.problems(
                "web-app-c#0@compose+multi",
                modes=("compose",),
                network_input="auto",
                vpn_mode="auto",
                distros=axes.DISTROS,
                filesystems=axes.FILESYSTEMS,
                lifecycles="",
                label="priority",
            )

    def test_a_role_without_a_bond_may_pin_multi_when_its_deploy_pulls_tor(
        self,
    ) -> None:
        tor = network.tor_provider()
        self.assertEqual(self._bondless_multi([tor], (tor,)), ([], []))

    def test_multi_is_judged_on_what_the_variant_deploys_not_on_discovery(
        self,
    ) -> None:
        errors, _warnings = self._bondless_multi([network.tor_provider()], ())
        self.assertIn("pinned network mode 'multi' is impossible", errors[0])

    def test_a_warning_still_separates_a_missing_role_from_a_present_one(self) -> None:
        _errors, warnings = _problems("web-app-a web-app-gone web-app-b")
        self.assertEqual(len(warnings), 1)
        self.assertIn("web-app-gone", warnings[0])

    def test_a_mode_the_row_does_not_offer_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-a#1@swarm+clearnet")
        self.assertIn("pinned mode 'swarm' is not available", errors[0])

    def test_a_network_mode_the_variant_rules_out_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-a#1@compose+tor")
        self.assertIn("pinned network mode 'tor' is impossible", errors[0])

    def test_a_network_mode_the_runs_network_axis_rules_out_is_an_error(self) -> None:
        errors, _warnings = _problems(
            "web-app-a#0@compose+clearnet", network_input="tor"
        )
        self.assertIn("pinned network mode 'clearnet' is impossible", errors[0])

    def test_a_network_mode_the_roles_reachability_rules_out_is_an_error(self) -> None:
        self.assertEqual(_problems("web-app-b#0@swarm+tor"), ([], []))
        errors, _warnings = _problems("web-app-b#0@swarm+multi")
        self.assertIn("pinned network mode 'multi' is impossible", errors[0])

    def test_a_mesh_state_the_mode_rules_out_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-a#0@compose+clearnet&vpn")
        self.assertIn("pinned mesh state vpn is impossible", errors[0])

    def test_a_mesh_state_the_mode_allows_passes(self) -> None:
        self.assertEqual(_problems("web-app-a#0@swarm+clearnet&vpn"), ([], []))

    def test_every_offender_is_reported_not_just_the_first(self) -> None:
        errors, _warnings = _problems(
            "web-app-a#7@compose+tor web-app-a#1@swarm+tor web-app-b#9@swarm+tor"
        )
        self.assertEqual(len(errors), 3)

    def test_a_csv_token_is_checked_variant_by_variant(self) -> None:
        errors, _warnings = _problems("web-app-a#0,7@compose+clearnet")
        self.assertEqual(len(errors), 1)
        self.assertIn("matches no discovered row", errors[0])

    def test_a_priority_variant_the_network_axis_leaves_nothing_is_an_error(
        self,
    ) -> None:
        errors, _warnings = _problems("web-app-b#0@swarm", network_input="multi")
        self.assertEqual(len(errors), 1)
        self.assertIn(_NOTHING_LEFT, errors[0])

    def test_the_same_priority_variant_under_a_network_it_can_take_passes(
        self,
    ) -> None:
        self.assertEqual(_problems("web-app-b#0@swarm", network_input="auto"), ([], []))

    def test_a_bare_priority_role_no_variant_can_deploy_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-b", network_input="multi")
        self.assertEqual(len(errors), 1)
        self.assertIn(_NOTHING_LEFT, errors[0])

    def test_a_bare_priority_role_passes_while_one_variant_can_deploy(self) -> None:
        self.assertEqual(_problems("web-app-a", network_input="tor"), ([], []))

    def test_a_whitelist_token_is_not_held_to_the_priority_rule(self) -> None:
        self.assertEqual(
            _problems("web-app-b#0@swarm", network_input="multi", whitelist=True),
            ([], []),
        )


class TestMain(unittest.TestCase):
    def _main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(validate.query, "discover_rows", return_value=_ROWS),
            mock.patch.object(validate, "get_variants", return_value=_VARIANTS),
            mock.patch.object(
                validate.matrix, "deployed_rounds", return_value=_NOTHING_DEPLOYED
            ),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = validate.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_valid_selection_exits_zero(self) -> None:
        code, out, _err = self._main(["--priority", "web-app-a#0@swarm+tor"])
        self.assertEqual(code, 0)
        self.assertIn("valid for this branch", out)

    def test_an_unusable_selection_exits_non_zero(self) -> None:
        code, _out, err = self._main(["--priority", "web-app-a#7"])
        self.assertEqual(code, 1)
        self.assertIn("::error::", err)

    def test_the_network_flag_is_the_runs_network_axis(self) -> None:
        code, _out, err = self._main(
            ["--network", "clearnet", "--priority", "web-app-a#0@swarm+tor"]
        )
        self.assertEqual(code, 1)
        self.assertIn("pinned network mode 'tor' is impossible", err)

    def test_both_inputs_are_checked_and_named_in_the_message(self) -> None:
        code, _out, err = self._main(
            ["--whitelist", "web-app-a#7", "--priority", "web-app-b#9"]
        )
        self.assertEqual(code, 1)
        self.assertIn("whitelist:", err)
        self.assertIn("priority:", err)

    def test_a_priority_token_left_without_a_combination_fails_the_run(
        self,
    ) -> None:
        code, _out, err = self._main(
            ["--network", "multi", "--priority", "web-app-b#0@swarm"]
        )
        self.assertEqual(code, 1)
        self.assertIn(_NOTHING_LEFT, err)

    def test_the_same_token_in_the_whitelist_does_not_fail_the_run(self) -> None:
        code, _out, _err = self._main(
            ["--network", "multi", "--whitelist", "web-app-b#0@swarm"]
        )
        self.assertEqual(code, 0)

    def test_a_warning_alone_does_not_fail_the_run(self) -> None:
        code, out, _err = self._main(["--whitelist", "web-app-gone"])
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)


if __name__ == "__main__":
    unittest.main()
