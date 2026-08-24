from __future__ import annotations

import io
import unittest
import unittest.mock as mock
from contextlib import redirect_stderr, redirect_stdout

from cli.meta.ci import validate
from utils.github.variant import axes

_ROWS = [
    {"name": "web-app-a", "variant": 0, "test_compose": True, "test_swarm": True},
    {"name": "web-app-a", "variant": 1, "test_compose": True, "test_swarm": False},
    {"name": "web-app-b", "variant": 0, "test_compose": False, "test_swarm": True},
]

_VARIANTS = {
    "web-app-a": [{"services": {}}, {"services": {"tor": {"enabled": False}}}],
    "web-app-b": [{"services": {}}],
}


def _problems(tokens: str, *, tor_mode: str = "auto") -> tuple[list[str], list[str]]:
    with (
        mock.patch.object(validate.query, "discover_rows", return_value=_ROWS),
        mock.patch.object(validate, "get_variants", return_value=_VARIANTS),
    ):
        return validate.problems(
            tokens,
            modes=("compose", "swarm", "host"),
            tor_mode=tor_mode,
            distros=axes.DISTROS,
            filesystems=axes.FILESYSTEMS,
            lifecycles="",
            label="priority",
        )


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

    def test_a_mode_the_row_does_not_offer_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-a#1@swarm+clearnet")
        self.assertIn("pinned mode 'swarm' is not available", errors[0])

    def test_an_onion_state_the_variant_rules_out_is_an_error(self) -> None:
        errors, _warnings = _problems("web-app-a#1@compose+tor")
        self.assertIn("pinned onion state tor is impossible", errors[0])

    def test_an_onion_state_the_runs_tor_axis_rules_out_is_an_error(self) -> None:
        errors, _warnings = _problems(
            "web-app-a#0@compose+clearnet", tor_mode="enforced"
        )
        self.assertIn("pinned onion state clearnet is impossible", errors[0])

    def test_every_offender_is_reported_not_just_the_first(self) -> None:
        errors, _warnings = _problems(
            "web-app-a#7@compose+tor web-app-a#1@swarm+tor web-app-b#9@swarm+tor"
        )
        self.assertEqual(len(errors), 3)

    def test_a_csv_token_is_checked_variant_by_variant(self) -> None:
        errors, _warnings = _problems("web-app-a#0,7@compose+clearnet")
        self.assertEqual(len(errors), 1)
        self.assertIn("matches no discovered row", errors[0])


class TestMain(unittest.TestCase):
    def _main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(validate.query, "discover_rows", return_value=_ROWS),
            mock.patch.object(validate, "get_variants", return_value=_VARIANTS),
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

    def test_both_inputs_are_checked_and_named_in_the_message(self) -> None:
        code, _out, err = self._main(
            ["--whitelist", "web-app-a#7", "--priority", "web-app-b#9"]
        )
        self.assertEqual(code, 1)
        self.assertIn("whitelist:", err)
        self.assertIn("priority:", err)

    def test_a_warning_alone_does_not_fail_the_run(self) -> None:
        code, out, _err = self._main(["--whitelist", "web-app-gone"])
        self.assertEqual(code, 0)
        self.assertIn("::warning::", out)


if __name__ == "__main__":
    unittest.main()
