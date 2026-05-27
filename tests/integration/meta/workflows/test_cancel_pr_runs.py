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
EMPTY_RUNS_JSON = '{"workflow_runs":[]}\n'


@unittest.skipUnless(
    shutil.which("jq"), "jq is required for the shell script under test"
)
class TestCancelPullRequestRuns(unittest.TestCase):
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

                if [[ "${method}" == "POST" ]]; then
                    run_id="$(printf '%s\\n' "${url}" | sed -E 's#.*/actions/runs/([0-9]+)/cancel#\\1#')"
                    printf '%s\\n' "${run_id}" >> "${GH_FAKE_CANCEL_LOG}"
                    exit 0
                fi

                status="$(printf '%s\\n' "${url}" | sed -nE 's#.*[?&]status=([^&]+).*#\\1#p')"
                cat "${GH_FAKE_RUNS_DIR}/${status}.json"
                """
            ),
            encoding="utf-8",
        )
        fake_gh.chmod(0o755)

    def _run_script(
        self,
        *,
        runs_by_status,
        pr_head_ref="feature/makefile-wsl2",
        pr_head_sha="deadbeef",
        pr_head_repository="AlejandroRomanIbanez/core",
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

            self._write_fake_gh(temp_dir)

            env = os.environ.copy()
            env.update(
                {
                    "PR_NUMBER": "106",
                    "PR_HEAD_REF": pr_head_ref,
                    "PR_HEAD_SHA": pr_head_sha,
                    "PR_HEAD_REPOSITORY": pr_head_repository,
                    "GH_TOKEN": "test-token",
                    "REPOSITORY": "kevinveenbirkenbach/infinito-nexus",
                    "CURRENT_RUN_ID": "6",
                    "GH_FAKE_RUNS_DIR": str(runs_dir),
                    "GH_FAKE_CANCEL_LOG": str(cancel_log),
                    "PATH": f"{temp_dir}:{env['PATH']}",
                }
            )

            result = subprocess.run(
                ["bash", str(SCRIPT_PATH)],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            cancelled = []
            if cancel_log.exists():
                cancelled = [
                    line.strip()
                    for line in read_text(str(cancel_log)).splitlines()
                    if line.strip()
                ]
            return result, cancelled

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


if __name__ == "__main__":
    unittest.main()
