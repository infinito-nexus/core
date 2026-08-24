from __future__ import annotations

import io
import subprocess
import unittest
import unittest.mock as mock
from contextlib import redirect_stdout

from cli.administration.deploy.ci import gh, runs
from cli.administration.deploy.ci.trigger import __main__ as trigger
from cli.meta.ci import matrix
from tests.utils.ci.job_names import deploy_job_name
from tests.utils.ci.run_name import render
from utils.github.variant.pools import DISTROS


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

_AXES = f"%{DISTROS[0]}"
"""The distro glyph _JOBS carry, spelled back out as ASCII. The filesystem is
deliberately absent: a title states the assigned kind, not the effective one."""

_FAILED_TOKENS = (
    f"web-app-x#0,1@swarm+clearnet{_AXES} web-app-y#0,1@compose+clearnet{_AXES}"
)
"""What _JOBS failed at, exactly: x in swarm, y in compose, both on variant
shard 0,1, both on the clearnet and both on the same distro."""

_RUN_URL = "https://github.com/o/r/actions/runs/55"  # nocheck: url
_SOURCE_CONFIG = {
    "distros": "arch centos",
    "mode": "swarm",
    "lifecycles": "stable",
    "filesystem": "btrfs",
    "chunk_gate": "false",
    "workspace": "false",
}
_SOURCE_RUN = {"jobs": _JOBS, "displayTitle": render(_SOURCE_CONFIG)}


class TestTriggerMain(unittest.TestCase):
    def _run(
        self,
        argv: list[str],
        run: dict | None = None,
        inputs: dict[str, str] | None = None,
    ) -> tuple[int, list]:
        calls: list[tuple] = []
        buf = io.StringIO()
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(runs, "find_last_deploy_run", return_value=run),
            mock.patch.object(runs, "inputs_from_jobs", return_value=inputs or {}),
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append((wf, ref, wl, priority, config, repo))
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
            calls, [("entry-manual-steer.yml", "feature/x", "__ALL__", "", {}, "o/r")]
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
        self.assertEqual(calls[0][3], _FAILED_TOKENS)

    def test_a_leftover_scope_argument_no_longer_narrows_the_modes(self) -> None:
        for scope in ("swarm", "compose", "total"):
            with self.subTest(scope=scope):
                _rc, calls = self._run(["--failed", scope], run={"_jobs": _JOBS})
                self.assertEqual(calls[0][3], _FAILED_TOKENS)

    def test_every_failed_mode_of_one_role_comes_back_separately(self) -> None:
        both = [
            _job("docker", "web-app-x", "failure"),
            _job("swarm", "web-app-x", "failure"),
        ]
        _rc, calls = self._run(["--failed"], run={"_jobs": both})
        self.assertEqual(
            calls[0][3],
            f"web-app-x#0,1@compose+clearnet{_AXES} web-app-x#0,1@swarm+clearnet{_AXES}",
        )

    def test_never_deployed_priority_roles_join_the_retrigger(self) -> None:
        source = {"jobs": _JOBS, "displayTitle": render(_SOURCE_CONFIG)}
        calls: list = []
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=source),
            mock.patch.object(
                runs,
                "inputs_from_jobs",
                return_value={"priority": "web-app-x web-app-never"},
            ),
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append(priority)
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", _RUN_URL])
        self.assertEqual(rc, 0)
        self.assertEqual(
            calls[0],
            f"web-app-never {_FAILED_TOKENS}",
        )

    def test_an_unreadable_job_log_aborts_instead_of_dropping_the_priority(
        self,
    ) -> None:
        source = {
            "jobs": _JOBS,
            "displayTitle": render({**_SOURCE_CONFIG, "priority": "web-app-x"}),
        }
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=source),
            mock.patch.object(runs, "inputs_from_jobs", return_value={}),
            redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            trigger.main(["--failed", "--run", _RUN_URL])

    def test_a_never_deployed_priority_role_alone_still_dispatches(self) -> None:
        green = [
            _job("docker", "web-app-x", "success"),
            _job("swarm", "web-app-x", "success"),
        ]
        source = {"jobs": green, "displayTitle": render({})}
        calls: list = []
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=source),
            mock.patch.object(
                runs,
                "inputs_from_jobs",
                return_value={"priority": "web-app-x web-app-never"},
            ),
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append(priority)
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", _RUN_URL])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], "web-app-never")

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
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=_SOURCE_RUN) as fetch,
            mock.patch.object(runs, "find_last_deploy_run") as find_last,
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append((priority, config))
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", _RUN_URL])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], (_FAILED_TOKENS, _SOURCE_CONFIG))
        fetch.assert_called_once()
        find_last.assert_not_called()

    def test_failed_with_bare_run_id_resolves_against_branch_repo(self) -> None:
        calls: list = []
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=_SOURCE_RUN) as fetch,
            mock.patch.object(runs, "find_last_deploy_run") as find_last,
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append((priority, config))
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--failed", "--run", "55"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], (_FAILED_TOKENS, _SOURCE_CONFIG))
        fetch.assert_called_once_with("55", repo="o/r")
        find_last.assert_not_called()

    def test_apps_with_a_run_reproduces_its_configuration(self) -> None:
        calls: list = []
        with (
            mock.patch.object(gh, "current_branch", return_value="feature/x"),
            mock.patch.object(gh, "resolve_repo", return_value="o/r"),
            mock.patch.object(gh, "fetch_run", return_value=_SOURCE_RUN),
            mock.patch.object(matrix, "entries_of", return_value=[]),
            mock.patch.object(
                runs,
                "dispatch_workflow",
                side_effect=lambda wf, ref, wl="", priority="", config=None, repo=None: (
                    calls.append((wl, priority, config))
                ),
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = trigger.main(["--apps", "web-app-a", "--run", _RUN_URL])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], ("web-app-a", "", _SOURCE_CONFIG))

    def test_failed_no_run_found(self) -> None:
        rc, calls = self._run(["--failed"], run=None)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])

    def test_apps_and_failed_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit) as ctx, redirect_stdout(io.StringIO()):
            trigger.main(["--failed", "--apps", "x"])
        self.assertEqual(ctx.exception.code, 2)


class TestBranchRemote(unittest.TestCase):
    def _resolve(self, upstream: str | None, push_default: str | None) -> str:
        remotes = "fork\norigin"

        def fake_run(args: list[str]) -> str:
            if args[1] == "rev-parse":
                if upstream is None:
                    raise subprocess.CalledProcessError(128, args)
                return upstream
            if args[1] == "remote" and len(args) == 2:
                return remotes
            if args[1] == "config":
                if push_default is None:
                    raise subprocess.CalledProcessError(1, args)
                return push_default
            raise AssertionError(f"unexpected git call: {args}")

        with mock.patch.object(gh, "_run", side_effect=fake_run):
            return gh._branch_remote()

    def test_tracking_remote_wins(self) -> None:
        self.assertEqual(self._resolve("origin/main", "fork"), "origin")

    def test_push_default_beats_origin_without_upstream(self) -> None:
        self.assertEqual(self._resolve(None, "fork"), "fork")

    def test_origin_when_no_upstream_and_no_push_default(self) -> None:
        self.assertEqual(self._resolve(None, None), "origin")

    def test_unknown_push_default_is_ignored(self) -> None:
        self.assertEqual(self._resolve(None, "gone"), "origin")


if __name__ == "__main__":
    unittest.main()
