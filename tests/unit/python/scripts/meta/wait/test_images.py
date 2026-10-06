from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "meta" / "wait" / "images.sh"
HEAD_SHA = "5b002678df222f1095fae2f42e3bb10964adb8ef"
RUN_TITLE = "pull_request_target / PR #1 / synchronize / fork:branch"
STUBS = {
    "docker": '#!/usr/bin/env bash\n[[ -e "${STUB_DIR}/images-ready" ]]\n',
    "gh": (
        "#!/usr/bin/env bash\n"
        'printf "gh %s\\n" "$*" >&2\n'
        'if [[ -n "${STUB_IMAGES_APPEAR:-}" ]]; then\n'
        '\ttouch "${STUB_DIR}/images-ready"\n'
        "fi\n"
        'if [[ -e "${STUB_DIR}/gh-response" ]]; then\n'
        '\tcat "${STUB_DIR}/gh-response"\n'
        "\texit 0\n"
        "fi\n"
        'echo "HTTP 504" >&2\n'
        "exit 1\n"
    ),
}


def wait_for_images(
    tmp: str, runs: list[dict] | None = None, **overrides: str
) -> subprocess.CompletedProcess:
    """Run the wait script against stubbed ``docker`` and ``gh``.

    Args:
        tmp: directory that holds the stubs and their state.
        runs: workflow runs ``gh`` answers with; without them every lookup fails.
        overrides: environment entries layered over the defaults.
    """
    stub_dir = Path(tmp)
    for name, body in STUBS.items():
        stub = stub_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    if runs is not None:
        (stub_dir / "gh-response").write_text(json.dumps({"workflow_runs": runs}))
    inherited = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
    env = {
        **inherited,
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_DIR": str(stub_dir),
        "GITHUB_REPOSITORY": "acme/widgets",
        "GH_TOKEN": "unused",
        "WORKFLOW_FILE": "entry.yml",
        "TARGET_EVENT": "pull_request_target",
        "PR_NUMBER": "1",
        "PR_HEAD_SHA": HEAD_SHA,
        "IMAGE_TAG": "ci-test",
        "INFINITO_DISTROS": "debian",
        "WAIT_ATTEMPTS": "100",
        "WAIT_SLEEP_SECONDS": "0",
        **overrides,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestWaitForImages(unittest.TestCase):
    def test_failed_lookup_does_not_end_the_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = wait_for_images(tmp, STUB_IMAGES_APPEAR="true")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "Lookup of the privileged workflow run failed (1/30)", result.stdout
            )
            self.assertIn("All required CI images are available.", result.stdout)

    def test_lookup_that_keeps_failing_ends_the_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = wait_for_images(tmp)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("failed 30 times in a row", result.stderr)

    def test_failed_privileged_run_of_a_fork_ends_the_wait(self) -> None:
        fork_run = {
            "id": 7,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-10-04T12:41:18Z",
            "head_sha": HEAD_SHA,
            "display_title": RUN_TITLE,
            "pull_requests": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = wait_for_images(tmp, runs=[fork_run])
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "Privileged run 7 finished with conclusion=failure", result.stderr
            )
            self.assertIn(f"head_sha={HEAD_SHA}", result.stderr)

    def test_run_of_another_head_is_ignored(self) -> None:
        other_run = {
            "id": 8,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-10-04T12:41:18Z",
            "head_sha": "0" * 40,
            "display_title": RUN_TITLE,
            "pull_requests": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = wait_for_images(tmp, runs=[other_run], WAIT_ATTEMPTS="2")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(
                "No matching privileged workflow run found yet", result.stdout
            )
            self.assertIn("Timed out waiting for CI images", result.stderr)

    def test_run_of_another_pull_request_on_the_same_head_is_ignored(self) -> None:
        own_run = {
            "id": 7,
            "status": "in_progress",
            "conclusion": None,
            "created_at": "2026-10-04T12:41:18Z",
            "head_sha": HEAD_SHA,
            "display_title": RUN_TITLE,
            "pull_requests": [],
        }
        other_run = {
            "id": 9,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-10-04T12:45:00Z",
            "head_sha": HEAD_SHA,
            "display_title": "pull_request_target / PR #12 / synchronize / fork:branch",
            "pull_requests": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = wait_for_images(tmp, runs=[own_run, other_run], WAIT_ATTEMPTS="2")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("Privileged run 7 ", result.stdout)
            self.assertNotIn("Privileged run 9", result.stdout + result.stderr)
            self.assertIn("Timed out waiting for CI images", result.stderr)


if __name__ == "__main__":
    unittest.main()
