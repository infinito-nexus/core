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

    def test_a_run_that_deployed_nothing_starts_at_the_head(self) -> None:
        self.assertEqual(selections.resume_offset(self._REGULAR, set()), "")

    def test_the_offset_is_the_last_row_of_the_leading_run(self) -> None:
        deployed = {
            "web-app-a#0@compose+clearnet" + _AXES,
            "web-app-b#1@swarm+tor" + _AXES,
        }
        self.assertEqual(
            selections.resume_offset(self._REGULAR, deployed), "web-app-b#1"
        )

    def test_the_offset_carries_no_axes_so_it_survives_a_new_sweep(self) -> None:
        """Every axis rotates with the sweep number and a retrigger gets a
        fresh one, so an axis-pinned offset would resolve only in the sweep it
        was computed at and abort every chunk's discovery in the others."""
        deployed = {"web-app-a#0@compose+clearnet" + _AXES}
        offset = selections.resume_offset(self._REGULAR, deployed)
        self.assertNotIn("@", offset)
        self.assertNotIn("+", offset)
        self.assertNotIn("%", offset)
        self.assertNotIn("/", offset)

    def test_a_gap_stops_the_scan_rather_than_skipping_past_it(self) -> None:
        deployed = {
            "web-app-a#0@compose+clearnet" + _AXES,
            "web-app-c#0@host+clearnet" + _AXES,
        }
        self.assertEqual(
            selections.resume_offset(self._REGULAR, deployed), "web-app-a#0"
        )

    def test_a_run_that_covered_everything_resumes_at_the_last_row(self) -> None:
        deployed = {
            "web-app-a#0@compose+clearnet" + _AXES,
            "web-app-b#1@swarm+tor" + _AXES,
            "web-app-c#0@host+clearnet" + _AXES,
        }
        self.assertEqual(
            selections.resume_offset(self._REGULAR, deployed), "web-app-c#0"
        )

    def test_the_verdict_does_not_matter_only_that_the_row_ran(self) -> None:
        jobs = [
            _job(deploy_job_name("swarm", "web-app-b", "1", tor=True), "failure"),
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
        ]
        self.assertEqual(
            selections.deployed_selections(jobs),
            {"web-app-a#0@compose+clearnet" + _AXES, "web-app-b#1@swarm+tor" + _AXES},
        )


class TestUnrunSelections(unittest.TestCase):
    """The rows the source run never reached."""

    _REGULAR: ClassVar[list[dict]] = [
        _row("web-app-a", "0", "compose"),
        _row("web-app-b", "1", "swarm", tor=True),
        _row("web-app-c", "0", "host"),
    ]

    def test_a_row_with_no_job_comes_back_with_its_axes(self) -> None:
        deployed = {"web-app-a#0@compose+clearnet" + _AXES}
        self.assertEqual(
            selections.unrun_selections(self._REGULAR, deployed),
            ["web-app-b#1@swarm+tor" + _AXES, "web-app-c#0@host+clearnet" + _AXES],
        )

    def test_a_row_deployed_under_other_axes_counts_as_run(self) -> None:
        """Mode, tor and distro rotate; comparing them calls every row unrun."""
        deployed = {f"web-app-b#1@compose+clearnet%{DISTROS[1]}"}
        self.assertNotIn(
            "web-app-b#1@swarm+tor" + _AXES,
            selections.unrun_selections(self._REGULAR, deployed),
        )

    def test_run_and_unrun_partition_the_ranking(self) -> None:
        deployed = {"web-app-a#0@compose+clearnet" + _AXES}
        unrun = selections.unrun_selections(self._REGULAR, deployed)
        self.assertEqual(len(unrun) + 1, len(self._REGULAR))

    def test_a_run_that_deployed_nothing_owes_every_row(self) -> None:
        self.assertEqual(
            len(selections.unrun_selections(self._REGULAR, set())), len(self._REGULAR)
        )


class TestSettledSelections(unittest.TestCase):
    """Only a green or a red row retires a combination."""

    def test_a_success_and_a_failure_both_settle(self) -> None:
        jobs = [
            _job(deploy_job_name("docker", "web-app-a", "0"), "success"),
            _job(deploy_job_name("swarm", "web-app-b", "1", tor=True), "failure"),
        ]
        self.assertEqual(
            selections.settled_selections(jobs),
            {"web-app-a#0@compose+clearnet" + _AXES, "web-app-b#1@swarm+tor" + _AXES},
        )

    def test_a_cancelled_row_settles_nothing(self) -> None:
        jobs = [_job(deploy_job_name("docker", "web-app-a", "0"), "cancelled")]
        self.assertEqual(selections.settled_selections(jobs), set())
        self.assertEqual(len(selections.deployed_selections(jobs)), 1)

    def test_a_still_running_row_settles_nothing(self) -> None:
        jobs = [_job(deploy_job_name("docker", "web-app-a", "0"), None, "in_progress")]
        self.assertEqual(selections.settled_selections(jobs), set())

    def test_an_aborted_row_comes_back_as_unrun(self) -> None:
        """It was never judged, so the combination is still owed an attempt."""
        regular = [_row("web-app-a", "0", "compose")]
        jobs = [_job(deploy_job_name("docker", "web-app-a", "0"), "cancelled")]
        self.assertEqual(
            selections.unrun_selections(regular, selections.settled_selections(jobs)),
            ["web-app-a#0@compose+clearnet" + _AXES],
        )
        self.assertEqual(
            selections.unrun_selections(regular, selections.deployed_selections(jobs)),
            [],
        )


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
