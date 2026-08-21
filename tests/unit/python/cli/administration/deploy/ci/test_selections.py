from __future__ import annotations

import unittest
from typing import ClassVar

from cli.administration.deploy.ci import selections
from tests.utils.ci.job_names import deploy_job_name
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
