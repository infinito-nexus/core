"""A retrigger reproduces its source run in every input but the selection.

``infinito administration deploy ci trigger --failed`` (the ``i8cifail``
family) re-dispatches ``entry-manual-steer.yml``. Two things have to hold, and
neither is visible in a green run:

* **Every dispatch input travels.** An input the source run set and the
  retrigger drops silently falls back to the workflow default, so the rerun
  deploys under a configuration nobody chose -- a swarm-only run coming back as
  a full rotation, a tor-enforced run coming back on the clearnet. The carried
  set is therefore derived from the workflow itself, and this test walks the
  same declaration: adding an input to the form without teaching the trigger
  fails here rather than in a run three hours later.
* **The priority line names what actually failed.** Aggregated to a role id, a
  retrigger redeploys whichever variant/mode/onion combination the rotation
  picks next, which need not be the one that broke. Each failed job comes back
  as its own selection token instead.
"""

from __future__ import annotations

import io
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from cli.administration.deploy.ci import gh, runs
from cli.administration.deploy.ci.trigger import __main__ as trigger
from cli.meta.ci import matrix
from tests.utils.ci.job_names import deploy_job_name
from utils.github.variant.pools import DISTROS

_REPO = "o/r"
_BRANCH = "feature/x"
_RUN_URL = "https://github.com/o/r/actions/runs/55"  # nocheck: url

_VALUES = {
    "distros": "arch debian",
    "priority": "web-app-seed",
    "whitelist": "web-app-x web-app-y",
    "lifecycles": "stable",
    "mode": "swarm",
    "filesystem": "btrfs",
    "tor": "enforced",
    "offset": "40",
    "chunk_gate": "false",
    "sweep": "7",
    "workspace": "true",
    "workspace_track": "compose",
    "instructions": "false",
}
"""A value for every dispatch input, distinct from that input's default so a
dropped one shows up as a missing key rather than as a coincidence."""

_JOBS = [
    {
        "name": deploy_job_name("swarm", "web-app-x", "0", tor=True),
        "status": "completed",
        "conclusion": "failure",
    },
    {
        "name": deploy_job_name("docker", "web-app-y", "1"),
        "status": "completed",
        "conclusion": "success",
    },
]


def _dispatch(argv: list[str], logged: dict[str, str]) -> tuple[str, str, dict]:
    """Run the trigger against a source run whose log records *logged*."""
    seen: list[tuple[str, str, dict]] = []
    source = {"jobs": _JOBS, "displayTitle": ""}
    with (
        mock.patch.object(gh, "current_branch", return_value=_BRANCH),
        mock.patch.object(gh, "resolve_repo", return_value=_REPO),
        mock.patch.object(gh, "fetch_run", return_value=source),
        mock.patch.object(runs, "inputs_from_jobs", return_value=logged),
        mock.patch.object(matrix, "entries_of", return_value=[]),
        mock.patch.object(
            runs,
            "dispatch_workflow",
            side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                seen.append((wl, priority, config or {}))
            ),
        ),
        redirect_stdout(io.StringIO()),
    ):
        assert trigger.main(argv) == 0
    assert seen, "the trigger dispatched nothing"
    return seen[0]


class TestCarriedInputs(unittest.TestCase):
    def test_the_carried_set_is_the_workflow_minus_the_priority_line(self) -> None:
        declared = set(runs.dispatch_inputs())
        self.assertTrue(declared, "entry-manual-steer.yml declares no inputs")
        self.assertEqual(set(runs.carried_inputs()), declared - {"priority", "offset"})

    def test_the_test_fixture_covers_every_declared_input(self) -> None:
        self.assertEqual(set(_VALUES), set(runs.dispatch_inputs()))

    def test_every_carried_input_reaches_the_dispatch_unchanged(self) -> None:
        whitelist, _priority, config = _dispatch(
            ["--failed", "--run", _RUN_URL], _VALUES
        )
        sent = {**config, "whitelist": whitelist}
        for name in runs.carried_inputs():
            with self.subTest(input=name):
                self.assertEqual(sent.get(name), _VALUES[name])

    def test_the_priority_line_is_not_carried_but_recomputed(self) -> None:
        _whitelist, priority, config = _dispatch(
            ["--failed", "--run", _RUN_URL], _VALUES
        )
        self.assertNotIn("priority", config)
        self.assertNotEqual(priority, _VALUES["priority"])

    def test_the_offset_is_not_carried_but_recomputed(self) -> None:
        _whitelist, _priority, config = _dispatch(
            ["--failed", "--run", _RUN_URL], _VALUES
        )
        self.assertNotEqual(config.get("offset"), _VALUES["offset"])

    def test_an_input_the_source_left_on_its_default_is_not_invented(self) -> None:
        _whitelist, _priority, config = _dispatch(
            ["--failed", "--run", _RUN_URL], {"tor": "exclusive"}
        )
        self.assertEqual(config.get("tor"), "exclusive")
        self.assertNotIn("mode", config)


class TestRecomputedSelection(unittest.TestCase):
    def test_the_priority_line_replays_the_exact_failed_selection(self) -> None:
        _whitelist, priority, _config = _dispatch(
            ["--failed", "--run", _RUN_URL], {"priority": ""}
        )
        self.assertEqual(priority, f"web-app-x#0@swarm+tor%{DISTROS[0]}")

    def test_a_green_selection_of_the_same_run_is_left_alone(self) -> None:
        _whitelist, priority, _config = _dispatch(
            ["--failed", "--run", _RUN_URL], {"priority": ""}
        )
        self.assertNotIn("web-app-y", priority)

    def test_the_scope_of_the_source_run_survives_the_retrigger(self) -> None:
        whitelist, _priority, _config = _dispatch(
            ["--failed", "--run", _RUN_URL], _VALUES
        )
        self.assertEqual(whitelist, _VALUES["whitelist"])


if __name__ == "__main__":
    unittest.main()
