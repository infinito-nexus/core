from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.ci import selections
from tests.utils.ci.job_names import deploy_job_name
from utils.github.variant import selection
from utils.github.variant.pools import DISTROS, FILESYSTEMS


def _job(name: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def _row(app: str, variant: str, mode: str, tor: bool = False) -> dict:
    return {
        "apps": app,
        "variant": variant,
        "mode": mode,
        "tor": "true" if tor else "false",
        "distro": DISTROS[0],
        "filesystem": FILESYSTEMS[0],
        "priority": "false",
    }


_AXES = f"%{DISTROS[0]}"


class TestResumeOffset(unittest.TestCase):
    """Where a retrigger picks the regular line up again."""

    _REGULAR: ClassVar[list[dict]] = [
        _row("web-app-a", "0", "compose"),
        _row("web-app-b", "1", "swarm", tor=True),
        _row("web-app-c", "0", "host"),
    ]

    def test_a_row_proven_under_the_source_sweeps_axes_still_counts(self) -> None:
        """The retrigger is a new run with a new sweep number, so its ranking
        assigns row a a different mode, onion state and distro than the run
        that proved it. Comparing the full tokens stopped every walk on its
        first row and pinned the regular line to the head forever."""
        jobs = [_job(deploy_job_name("swarm", "web-app-a", "0", tor=True), "success")]
        self.assertEqual(
            selections.resume_offset(self._REGULAR, selections.proven_rows(jobs)),
            "web-app-a#0",
        )

    def test_a_run_that_deployed_nothing_starts_at_the_head(self) -> None:
        self.assertEqual(selections.resume_offset(self._REGULAR, set()), "")

    def test_the_offset_is_the_last_row_of_the_leading_run(self) -> None:
        proven = {"web-app-a#0", "web-app-b#1"}
        self.assertEqual(selections.resume_offset(self._REGULAR, proven), "web-app-b#1")

    def test_a_red_row_stops_the_scan_so_the_line_walks_it_again(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-b", "1", tor=True), "failure"),
            _job(deploy_job_name("host", "web-app-c", "0"), "success"),
        ]
        self.assertEqual(
            selections.resume_offset(self._REGULAR, selections.proven_rows(jobs)),
            "web-app-a#0",
        )

    def test_the_offset_carries_no_axes_so_it_survives_a_new_sweep(self) -> None:
        """Every axis rotates with the sweep number and a retrigger gets a
        fresh one, so an axis-pinned offset would resolve only in the sweep it
        was computed at and abort every chunk's discovery in the others."""
        offset = selections.resume_offset(self._REGULAR, {"web-app-a#0"})
        self.assertNotIn("@", offset)
        self.assertNotIn("+", offset)
        self.assertNotIn("%", offset)
        self.assertNotIn("/", offset)

    def test_a_gap_stops_the_scan_rather_than_skipping_past_it(self) -> None:
        proven = {"web-app-a#0", "web-app-c#0"}
        self.assertEqual(selections.resume_offset(self._REGULAR, proven), "web-app-a#0")

    def test_a_run_that_covered_everything_resumes_at_the_last_row(self) -> None:
        self.assertEqual(
            selections.resume_offset(self._REGULAR, self._ALL_PROVEN), "web-app-c#0"
        )

    _ALL_PROVEN: ClassVar[set[str]] = {"web-app-a#0", "web-app-b#1", "web-app-c#0"}

    def test_a_role_the_priority_line_takes_whole_is_never_the_offset(self) -> None:
        """A variant-less pin blacklists its whole role from the regular query,
        so an offset naming one of its rows resolves against nothing."""
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR, self._ALL_PROVEN, selection.parse_list("web-app-c")
            ),
            "web-app-b#1",
        )

    def test_a_variant_the_priority_line_pins_is_never_the_offset(self) -> None:
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR, self._ALL_PROVEN, selection.parse_list("web-app-c#0")
            ),
            "web-app-b#1",
        )

    def test_a_pin_on_another_variant_leaves_the_row_offsettable(self) -> None:
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR, self._ALL_PROVEN, selection.parse_list("web-app-c#4")
            ),
            "web-app-c#0",
        )

    def test_a_claimed_row_mid_line_does_not_stop_the_scan(self) -> None:
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR, self._ALL_PROVEN, selection.parse_list("web-app-b")
            ),
            "web-app-c#0",
        )

    def test_every_green_row_claimed_starts_at_the_head(self) -> None:
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR,
                self._ALL_PROVEN,
                selection.parse_list("web-app-a web-app-b web-app-c"),
            ),
            "",
        )


class TestCarriedOffset(unittest.TestCase):
    """A retrigger inherits the window its source run was given."""

    _REGULAR: ClassVar[list[dict]] = [
        _row("web-app-a", "0", "compose"),
        _row("web-app-b", "1", "swarm", tor=True),
        _row("web-app-c", "0", "host"),
    ]

    def test_nothing_green_behind_the_carried_offset_keeps_it(self) -> None:
        self.assertEqual(
            selections.resume_offset(self._REGULAR, set(), carried="web-app-b#1"),
            "web-app-b#1",
        )

    def test_the_green_stretch_behind_it_moves_it_forward(self) -> None:
        proven = {"web-app-b#1", "web-app-c#0"}
        self.assertEqual(
            selections.resume_offset(self._REGULAR, proven, carried="web-app-b#1"),
            "web-app-c#0",
        )

    def test_a_red_row_at_the_carried_offset_is_left_to_its_claim(self) -> None:
        """The priority line takes the whole role, so naming that row would
        emit an offset resolving against nothing; the next free row is the
        answer, and it is still ahead of where the source run started."""
        jobs = [_job(deploy_job_name("swarm", "web-app-b", "1", tor=True), "failure")]
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR,
                selections.proven_rows(jobs),
                selection.parse_list("web-app-b"),
                carried="web-app-b#1",
            ),
            "web-app-c#0",
        )

    def test_a_row_count_anchors_the_window_too(self) -> None:
        self.assertEqual(
            selections.resume_offset(self._REGULAR, set(), carried="2"), "web-app-c#0"
        )

    def test_a_vanished_token_falls_forward_to_the_first_green_row(self) -> None:
        self.assertEqual(
            selections.resume_offset(
                self._REGULAR, {"web-app-c#0"}, carried="web-app-gone#0"
            ),
            "web-app-c#0",
        )

    def test_a_vanished_token_with_nothing_green_starts_at_the_head(self) -> None:
        self.assertEqual(
            selections.resume_offset(self._REGULAR, set(), carried="web-app-gone#0"), ""
        )


class TestProvenRows(unittest.TestCase):
    """Only a row green in every combination it ran lets the line walk past."""

    def test_only_the_successes_are_kept(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-b", "1", tor=True), "failure"),
            _job(deploy_job_name("host", "web-app-c", "0"), "cancelled"),
        ]
        self.assertEqual(selections.proven_rows(jobs), {"web-app-a#0"})

    def test_the_axes_are_dropped_so_the_row_survives_a_new_sweep(self) -> None:
        jobs = [_job(deploy_job_name("swarm", "web-app-a", "0", tor=True), "success")]
        self.assertEqual(selections.proven_rows(jobs), {"web-app-a#0"})

    def test_one_red_axis_un_proves_the_whole_row(self) -> None:
        """A priority row deploys its whole cross-product, so one role#variant
        can carry several verdicts; a green compose job must not carry a red
        swarm one past the regular line."""
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-a", "0", tor=True), "failure"),
        ]
        self.assertEqual(selections.proven_rows(jobs), set())

    def test_one_aborted_axis_un_proves_it_too(self) -> None:
        """It reached no verdict, which is the same reason a lone aborted row
        stops the walk."""
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-a", "0", tor=True), "cancelled"),
        ]
        self.assertEqual(selections.proven_rows(jobs), set())

    def test_a_red_axis_of_one_variant_leaves_its_siblings_alone(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "failure"),
            _job(deploy_job_name("docker", "web-app-a", "1"), "success"),
        ]
        self.assertEqual(selections.proven_rows(jobs), {"web-app-a#1"})


class TestCollapseToRoles(unittest.TestCase):
    """Trading the exact red combination for covering the role."""

    def test_the_combinations_of_one_role_become_one_entry(self) -> None:
        collapsed = selections.collapse_to_roles(
            [
                "web-app-a#0@compose+clearnet" + _AXES,
                "web-app-a#1@swarm+tor" + _AXES,
                "web-app-b#0@swarm+clearnet" + _AXES,
            ]
        )
        self.assertEqual(collapsed, ["web-app-a", "web-app-b"])

    def test_nothing_stays_pinned(self) -> None:
        """A leftover axis would pin the rotation to a combination nobody chose."""
        for token in selections.collapse_to_roles(
            ["web-app-a#2@swarm+tor" + _AXES, "web-app-b#0@compose+clearnet" + _AXES]
        ):
            with self.subTest(token=token):
                self.assertFalse(selection.parse(token).pinned)

    def test_no_role_is_dropped(self) -> None:
        tokens = [
            f"web-app-{name}#0@compose+clearnet{_AXES}" for name in ("a", "b", "c")
        ]
        self.assertEqual(len(selections.collapse_to_roles(tokens)), len(tokens))

    def test_an_already_bare_role_survives_unchanged(self) -> None:
        """An untriggered priority entry may already carry no axes."""
        self.assertEqual(selections.collapse_to_roles(["web-app-a"]), ["web-app-a"])
