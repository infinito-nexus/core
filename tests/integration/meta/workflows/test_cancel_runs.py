import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "scripts" / "github" / "cancel" / "pull_request_runs.sh"
BRANCH_SCRIPT_PATH = PROJECT_ROOT / "scripts" / "github" / "cancel" / "branch_runs.sh"
EMPTY_RUNS_JSON = '{"workflow_runs":[]}\n'


class CancelScriptMixin:
    def _write_fake_gh(self, temp_dir: Path) -> None:
        fake_gh = temp_dir / "gh"
        fake_gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                if [[ "${1:-}" != "api" ]]; then
                    echo "Unsupported gh invocation: $*" >&2
                    exit 1
                fi
                shift

                method="GET"
                url=""
                while [[ $# -gt 0 ]]; do
                    case "$1" in
                        --paginate)
                            shift
                            ;;
                        -H)
                            shift 2
                            ;;
                        -X)
                            method="$2"
                            shift 2
                            ;;
                        /repos/*)
                            url="$1"
                            shift
                            ;;
                        *)
                            shift
                            ;;
                    esac
                done

                if [[ "${method}" == "POST" && "${url}" == */force-cancel ]]; then
                    printf '%s\\n' "${url}" \
                        | sed -E 's#.*/actions/runs/([0-9]+)/force-cancel#\\1#' \
                        >> "${GH_FAKE_FORCE_LOG}"
                    exit 0
                fi

                if [[ "${method}" == "POST" ]]; then
                    run_id="$(printf '%s\\n' "${url}" | sed -E 's#.*/actions/runs/([0-9]+)/cancel#\\1#')"
                    if [[ -n "${GH_FAKE_POST_ERROR:-}" ]]; then
                        echo "${GH_FAKE_POST_ERROR}" >&2
                        exit 1
                    fi
                    if [[ -n "${GH_FAKE_POST_ERROR_ONCE:-}" \\
                          && ! -f "${GH_FAKE_CANCEL_LOG}.once" ]]; then
                        touch "${GH_FAKE_CANCEL_LOG}.once"
                        echo "${GH_FAKE_POST_ERROR_ONCE}" >&2
                        exit 1
                    fi
                    printf '%s\\n' "${run_id}" >> "${GH_FAKE_CANCEL_LOG}"
                    exit 0
                fi

                if [[ "${url}" == */actions/runs/[0-9]* ]]; then
                    printf '%s\\n' "${GH_FAKE_RUN_STATUS:-completed}"
                    exit 0
                fi

                if [[ "${url}" == */pulls* ]]; then
                    cat "${GH_FAKE_RUNS_DIR}/pulls.json"
                    exit 0
                fi

                status="$(printf '%s\\n' "${url}" | sed -nE 's#.*[?&]status=([^&]+).*#\\1#p')"
                if [[ "${status}" == "${GH_FAKE_GET_ERROR_STATUS:-}" ]]; then
                    echo "gh: simulated API failure for ${status}" >&2
                    exit 1
                fi
                cat "${GH_FAKE_RUNS_DIR}/${status}.json"
                """
            ),
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

    def _run_cancel_script(
        self, script_path, env_overrides, runs_by_status, check=True
    ):
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            cancel_log = temp_dir / "cancel.log"

            for status in ["requested", "pending", "waiting", "queued", "in_progress"]:
                (runs_dir / f"{status}.json").write_text(
                    runs_by_status.get(status, EMPTY_RUNS_JSON),
                    encoding="utf-8",
                )
            (runs_dir / "pulls.json").write_text(
                runs_by_status.get("pulls", "[]\n"), encoding="utf-8"
            )

            self._write_fake_gh(temp_dir)

            env = os.environ.copy()
            env.update(
                {
                    "GH_TOKEN": "test-token",
                    "REPOSITORY": "kevinveenbirkenbach/infinito-nexus",
                    "GH_FAKE_RUNS_DIR": str(runs_dir),
                    "GH_FAKE_CANCEL_LOG": str(cancel_log),
                    "GH_FAKE_FORCE_LOG": str(temp_dir / "force.log"),
                    "PATH": f"{temp_dir}:{env['PATH']}",
                    **env_overrides,
                }
            )

            result = subprocess.run(
                ["bash", str(script_path)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=check,
            )

            cancelled = []
            if cancel_log.exists():
                cancelled = [
                    line.strip()
                    for line in read_text(str(cancel_log)).splitlines()
                    if line.strip()
                ]
            force_log = temp_dir / "force.log"
            self.forced = []
            if force_log.exists():
                self.forced = [
                    line.strip()
                    for line in read_text(str(force_log)).splitlines()
                    if line.strip()
                ]
            return result, cancelled


@unittest.skipUnless(
    shutil.which("jq"), "jq is required for the shell script under test"
)
class TestCancelPullRequestRuns(CancelScriptMixin, unittest.TestCase):
    def _run_script(
        self,
        *,
        runs_by_status,
        pr_head_ref="feature/makefile-wsl2",
        pr_head_sha="deadbeef",
        pr_head_repository="AlejandroRomanIbanez/core",
        include_paths="",
        keep_newest_per="",
    ):
        return self._run_cancel_script(
            SCRIPT_PATH,
            {
                "PR_NUMBER": "106",
                "PR_HEAD_REF": pr_head_ref,
                "PR_HEAD_SHA": pr_head_sha,
                "PR_HEAD_REPOSITORY": pr_head_repository,
                "INCLUDE_PATHS": include_paths,
                "KEEP_NEWEST_PER": keep_newest_per,
                "CURRENT_RUN_ID": "6",
            },
            runs_by_status,
        )

    def test_cancels_matching_fork_run_when_pull_request_association_is_missing(self):
        in_progress_runs = """\
{"workflow_runs":[
  {
    "id": 297,
    "event": "pull_request",
    "head_sha": "merge-sha-not-pr-head",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": []
  }
]}
"""
        _, cancelled = self._run_script(
            runs_by_status={"in_progress": in_progress_runs}
        )
        self.assertEqual(cancelled, ["297"])

    def test_does_not_cancel_run_from_other_fork_with_same_branch_name(self):
        in_progress_runs = """\
{"workflow_runs":[
  {
    "id": 297,
    "event": "pull_request",
    "head_sha": "merge-sha-not-pr-head",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": []
  },
  {
    "id": 298,
    "event": "pull_request",
    "head_sha": "another-merge-sha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "someone-else/core"},
    "pull_requests": []
  }
]}
"""
        _, cancelled = self._run_script(
            runs_by_status={"in_progress": in_progress_runs}
        )
        self.assertEqual(cancelled, ["297"])

    def test_cancels_run_via_head_sha_when_branch_metadata_differs(self):
        in_progress_runs = """\
{"workflow_runs":[
  {
    "id": 299,
    "event": "pull_request_target",
    "head_sha": "deadbeef",
    "head_branch": "unexpected-branch-name",
    "head_repository": {"full_name": "base-repo/core"},
    "pull_requests": []
  }
]}
"""
        _, cancelled = self._run_script(
            runs_by_status={"in_progress": in_progress_runs}
        )
        self.assertEqual(cancelled, ["299"])

    NEWEST_PER_GROUP_RUNS = """\
{"workflow_runs":[
  {
    "id": 300,
    "event": "pull_request",
    "path": ".github/workflows/entry-pr-change-orchestrate.yml",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 106}]
  },
  {
    "id": 301,
    "event": "pull_request",
    "path": ".github/workflows/entry-pr-change-orchestrate.yml",
    "created_at": "2026-08-25T07:54:16Z",
    "head_sha": "newsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 106}]
  },
  {
    "id": 302,
    "event": "pull_request_target",
    "path": ".github/workflows/entry-pr-change-orchestrate.yml",
    "created_at": "2026-08-25T07:54:15Z",
    "head_sha": "newsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 106}]
  }
]}
"""

    FORK_SHAPED_RUNS = """\
{"workflow_runs":[
  {
    "id": 320,
    "event": "pull_request",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": []
  }
]}
"""

    def test_cancels_a_fork_run_when_the_head_is_unambiguous(self):
        _, cancelled = self._run_script(
            runs_by_status={"queued": self.FORK_SHAPED_RUNS}
        )
        self.assertEqual(cancelled, ["320"])

    def test_keeps_fork_runs_when_another_pull_request_shares_the_head(self):
        result, cancelled = self._run_script(
            runs_by_status={
                "queued": self.FORK_SHAPED_RUNS,
                "pulls": (
                    '[{"number": 106, "head": {"ref": "feature/makefile-wsl2"}},'
                    ' {"number": 107, "head": {"ref": "feature/makefile-wsl2"}}]\n'
                ),
            },
        )
        self.assertEqual(cancelled, [])
        self.assertIn("Branch fallback disabled", result.stdout)

    def test_cancels_a_run_whose_association_names_this_pull_request(self):
        queued_runs = """\
{"workflow_runs":[
  {
    "id": 310,
    "event": "pull_request",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"no_number_field": true}]
  }
]}
"""
        _, cancelled = self._run_script(runs_by_status={"queued": queued_runs})
        self.assertEqual(cancelled, ["310"])

    def test_keeps_a_run_associated_with_a_different_pull_request(self):
        queued_runs = """\
{"workflow_runs":[
  {
    "id": 311,
    "event": "pull_request",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 999}]
  }
]}
"""
        _, cancelled = self._run_script(runs_by_status={"queued": queued_runs})
        self.assertEqual(cancelled, [])

    DELETED_FORK_RUNS = """\
{"workflow_runs":[
  {
    "id": 330,
    "event": "pull_request",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": []
  }
]}
"""

    def test_cancels_runs_of_a_pull_request_whose_fork_was_deleted(self):
        _, cancelled = self._run_script(
            runs_by_status={"queued": self.DELETED_FORK_RUNS},
            pr_head_repository="",
        )
        self.assertEqual(cancelled, ["330"])

    def test_keeps_them_when_another_pull_request_shares_the_branch(self):
        result, cancelled = self._run_script(
            runs_by_status={
                "queued": self.DELETED_FORK_RUNS,
                "pulls": '[{"number": 107, "head": {"ref": "feature/makefile-wsl2"}}]\n',
            },
            pr_head_repository="",
        )
        self.assertEqual(cancelled, [])
        self.assertIn("Branch fallback disabled", result.stdout)

    def test_keeps_the_newest_run_of_every_event(self):
        _, cancelled = self._run_script(
            runs_by_status={"queued": self.NEWEST_PER_GROUP_RUNS},
            keep_newest_per="event",
        )
        self.assertEqual(cancelled, ["300"])

    def test_keeps_the_newest_run_even_when_the_head_sha_moved_on(self):
        _, cancelled = self._run_script(
            runs_by_status={"queued": self.NEWEST_PER_GROUP_RUNS},
            keep_newest_per="event",
            pr_head_sha="a-third-sha-nobody-has-a-run-for",
        )
        self.assertEqual(cancelled, ["300"])

    def test_keeps_pull_request_runs_outside_the_concurrency_group(self):
        queued_runs = """\
{"workflow_runs":[
  {
    "id": 302,
    "event": "pull_request",
    "path": ".github/workflows/entry-pr-change-orchestrate.yml",
    "head_sha": "cafebabe",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 106}]
  },
  {
    "id": 303,
    "event": "pull_request_target",
    "path": ".github/workflows/entry-pr-open-dependabot-close.yml",
    "head_sha": "cafebabe",
    "head_branch": "feature/makefile-wsl2",
    "head_repository": {"full_name": "AlejandroRomanIbanez/core"},
    "pull_requests": [{"number": 106}]
  }
]}
"""
        _, cancelled = self._run_script(
            runs_by_status={"queued": queued_runs},
            include_paths=".github/workflows/entry-pr-change-orchestrate.yml",
        )
        self.assertEqual(cancelled, ["302"])


@unittest.skipUnless(
    shutil.which("jq"), "jq is required for the shell script under test"
)
class TestCancelBranchRuns(CancelScriptMixin, unittest.TestCase):
    BRANCH_RUNS = """\
{"workflow_runs":[
  {
    "id": 400,
    "path": ".github/workflows/entry-push-latest.yml",
    "event": "push",
    "created_at": "2026-08-25T07:54:12Z",
    "head_sha": "newsha",
    "head_branch": "feature/svc-net-tor",
    "pull_requests": []
  },
  {
    "id": 401,
    "path": ".github/workflows/entry-manual-steer.yml",
    "event": "workflow_dispatch",
    "created_at": "2026-08-24T22:33:34Z",
    "head_sha": "oldsha",
    "head_branch": "feature/svc-net-tor",
    "pull_requests": []
  },
  {
    "id": 402,
    "path": ".github/workflows/entry-push-latest.yml",
    "event": "push",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "other-branch",
    "pull_requests": []
  },
  {
    "id": 403,
    "path": ".github/workflows/entry-push-latest.yml",
    "event": "push",
    "created_at": "2026-08-24T22:25:11Z",
    "head_sha": "oldsha",
    "head_branch": "feature/svc-net-tor",
    "pull_requests": []
  }
]}
"""

    def _run_script(self, check=True, **env_overrides):
        return self._run_cancel_script(
            BRANCH_SCRIPT_PATH,
            {"BRANCH": "feature/svc-net-tor", **env_overrides},
            {"queued": self.BRANCH_RUNS},
            check=check,
        )

    def test_tolerates_whitespace_around_allowlist_entries(self):
        _, cancelled = self._run_script(
            INCLUDE_PATHS="  .github/workflows/entry-manual-steer.yml  \n\n",
        )
        self.assertEqual(cancelled, ["401"])

    def test_fails_loudly_when_a_cancel_is_rejected(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_POST_ERROR="gh: HTTP 403: Resource not accessible by integration",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("ERROR: cancelling run", result.stderr)

    def test_accepts_a_run_that_already_finished(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_POST_ERROR="gh: HTTP 409: Conflict",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("already completed", result.stdout)

    def test_keeps_only_the_newest_run_of_the_whole_group(self):
        _, cancelled = self._run_script(KEEP_NEWEST_PER="all")
        self.assertEqual(sorted(cancelled), ["401", "403"])

    def test_rejects_an_unknown_grouping_mode(self):
        result, cancelled = self._run_script(check=False, KEEP_NEWEST_PER="true")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("KEEP_NEWEST_PER must be", result.stderr)

    def test_cancels_every_branch_run_without_exclusions(self):
        _, cancelled = self._run_script()
        self.assertEqual(cancelled, ["400", "401", "403"])

    def test_force_cancels_runs_that_ignore_the_cancel(self):
        _, cancelled = self._run_script(
            KEEP_NEWEST_PER="all",
            FORCE_CANCEL_AFTER_SECONDS="0",
            GH_FAKE_RUN_STATUS="in_progress",
        )
        self.assertEqual(sorted(cancelled), ["401", "403"])
        self.assertEqual(sorted(self.forced), ["401", "403"])

    def test_leaves_runs_that_ended_on_their_own(self):
        _, cancelled = self._run_script(
            KEEP_NEWEST_PER="all",
            FORCE_CANCEL_AFTER_SECONDS="0",
            GH_FAKE_RUN_STATUS="completed",
        )
        self.assertEqual(sorted(cancelled), ["401", "403"])
        self.assertEqual(self.forced, [])

    def test_never_force_cancels_without_the_knob(self):
        _, cancelled = self._run_script(
            KEEP_NEWEST_PER="all",
            GH_FAKE_RUN_STATUS="in_progress",
        )
        self.assertEqual(sorted(cancelled), ["401", "403"])
        self.assertEqual(self.forced, [])

    def test_rejects_a_non_numeric_force_cancel_delay(self):
        result, cancelled = self._run_script(
            check=False, FORCE_CANCEL_AFTER_SECONDS="soon"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("whole number of seconds", result.stderr)

    def test_keeps_runs_outside_the_concurrency_group(self):
        _, cancelled = self._run_script(
            INCLUDE_PATHS=".github/workflows/entry-manual-steer.yml\n",
        )
        self.assertEqual(cancelled, ["401"])

    def test_aborts_on_an_allowlist_that_lists_nothing(self):
        result, cancelled = self._run_script(check=False, INCLUDE_PATHS="  \n \n")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("lists no workflow path", result.stderr)

    def test_stays_green_when_only_some_cancels_are_rejected(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_POST_ERROR_ONCE="gh: HTTP 403: rate limit",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(cancelled), 2)
        self.assertIn("WARNING: 1 of 3 run(s) could not be cancelled", result.stderr)

    def test_a_single_transient_rejection_does_not_fail_the_job(self):
        result, cancelled = self._run_script(
            check=False,
            INCLUDE_PATHS=".github/workflows/entry-manual-steer.yml\n",
            GH_FAKE_POST_ERROR="gh: HTTP 404: Not Found",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertEqual(result.stdout.count("Cancelling run "), 1)

    def test_fails_loudly_when_a_run_listing_fails(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_GET_ERROR_STATUS="queued",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])

    def test_attempts_every_run_and_stays_green_on_transient_rejections(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_POST_ERROR="gh: HTTP 500: Internal Server Error",
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertEqual(result.stdout.count("Cancelling run "), 3)
        self.assertIn("3 of 3 run(s) could not be cancelled", result.stderr)

    def test_fails_when_the_token_may_not_cancel(self):
        result, cancelled = self._run_script(
            check=False,
            GH_FAKE_POST_ERROR="gh: Resource not accessible by integration (HTTP 403)",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(cancelled, [])
        self.assertIn("token may not cancel runs", result.stderr)


if __name__ == "__main__":
    unittest.main()
