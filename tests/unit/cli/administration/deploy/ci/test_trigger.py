from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from cli.administration.deploy.ci import runs
from cli.administration.deploy.ci.trigger import __main__ as trigger
from tests.utils.ci_job_names import deploy_job_name


def _job(mode: str, app: str, conclusion: str) -> dict:
    return {
        "name": deploy_job_name(mode, app, "0,1"),
        "status": "completed",
        "conclusion": conclusion,
    }


_JOBS = [
    _job("docker", "web-app-x", "success"),
    _job("swarm", "web-app-x", "failure"),
    _job("docker", "web-app-y", "failure"),
    _job("swarm", "web-app-y", "success"),
]

_RUN_URL = "https://github.com/o/r/actions/runs/55"  # nocheck: url


class TestTriggerMain(unittest.TestCase):
    def _run(self, argv: list[str], run: dict | None = None) -> tuple[int, list]:
        calls: list[tuple] = []
        buf = io.StringIO()
        with (
            mock.patch.object(runs, "current_branch", return_value="feature/x"),
            mock.patch.object(runs, "resolve_repo", return_value="o/r"),
            mock.patch.object(runs, "find_last_deploy_run", return_value=run),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", repo=None: calls.append(
                    (wf, ref, wl, priority, repo)
                ),
            ),
            redirect_stdout(buf),
        ):
            rc = trigger.main(argv)
        return rc, calls

    def test_default_triggers_all(self) -> None:
        rc, calls = self._run([])
        self.assertEqual(rc, 0)
        self.assertEqual(
            calls, [("entry-manual.yml", "feature/x", "__ALL__", "", "o/r")]
        )

    def test_apps_explicit_list(self) -> None:
        rc, calls = self._run(["--apps", "web-app-a  web-app-b"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0][2], "web-app-a web-app-b")
        self.assertEqual(calls[0][3], "")

    def test_failed_total_sends_priority_without_whitelist(self) -> None:
        rc, calls = self._run(["--failed"], run={"_jobs": _JOBS})
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0][2], "")
        self.assertEqual(calls[0][3], "web-app-x web-app-y")

    def test_failed_swarm_scope(self) -> None:
        _rc, calls = self._run(["--failed", "swarm"], run={"_jobs": _JOBS})
        self.assertEqual(calls[0][3], "web-app-x")

    def test_failed_compose_scope(self) -> None:
        _rc, calls = self._run(["--failed", "compose"], run={"_jobs": _JOBS})
        self.assertEqual(calls[0][3], "web-app-y")

    def test_failed_nothing_does_not_dispatch(self) -> None:
        green = [
            _job("docker", "web-app-x", "success"),
            _job("swarm", "web-app-x", "success"),
        ]
        rc, calls = self._run(["--failed"], run={"_jobs": green})
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])

    def test_failed_with_run_url_uses_that_run(self) -> None:
        calls: list = []
        with (
            mock.patch.object(runs, "current_branch", return_value="feature/x"),
            mock.patch.object(runs, "resolve_repo", return_value="o/r"),
            mock.patch.object(runs, "fetch_jobs", return_value=_JOBS) as fetch,
            mock.patch.object(runs, "find_last_deploy_run") as find_last,
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", repo=None: calls.append(
                    priority
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", _RUN_URL])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], "web-app-x web-app-y")
        fetch.assert_called_once()
        find_last.assert_not_called()

    def test_failed_with_bare_run_id_resolves_against_branch_repo(self) -> None:
        calls: list = []
        with (
            mock.patch.object(runs, "current_branch", return_value="feature/x"),
            mock.patch.object(runs, "resolve_repo", return_value="o/r"),
            mock.patch.object(runs, "fetch_jobs", return_value=_JOBS) as fetch,
            mock.patch.object(runs, "find_last_deploy_run") as find_last,
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", repo=None: calls.append(
                    priority
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", "55"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], "web-app-x web-app-y")
        fetch.assert_called_once_with("55", repo="o/r")
        find_last.assert_not_called()

    def test_failed_no_run_found(self) -> None:
        rc, calls = self._run(["--failed"], run=None)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])

    def test_apps_and_failed_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()):
            trigger.main(["--failed", "--apps", "x"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
