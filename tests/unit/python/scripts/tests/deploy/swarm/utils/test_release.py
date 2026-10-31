"""release.sh saves the act job's artefacts, then releases the cluster in every outcome."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

RELEASE = (
    PROJECT_ROOT / "scripts" / "tests" / "deploy" / "swarm" / "utils" / "release.sh"
)
MAKEFILE = PROJECT_ROOT / "Makefile"
DOCKER_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "docker %s\\n" "$*" >>"${STUB_LOG}"\n'
    'if [ "$1" = ps ]; then echo act-id; exit 0; fi\n'
    'if [ "$1" = cp ]; then\n'
    '  if [ -n "${STUB_CP_ERROR}" ]; then echo "${STUB_CP_ERROR}" >&2; exit 1; fi\n'
    "  exit 0\n"
    "fi\n"
)
TEARDOWN_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "teardown SWARM_NAME=%s KEEP=%s\\n" "${SWARM_NAME}" '
    '"${INFINITO_KEEP_SWARM_NODES}" >>"${STUB_LOG}"\n'
)
DOWN_ACT_STUB = '#!/usr/bin/env bash\nprintf "down_act_outer\\n" >>"${STUB_LOG}"\n'


def release(
    keep: str, drill_rc: int, cp_error: str = ""
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run release.sh around a drill that exits ``drill_rc``.

    Args:
        keep: the ``keep`` value make hands over.
        drill_rc: exit code of the stub drill.
        cp_error: stderr the stub ``docker cp`` fails with, empty for success.

    Returns:
        The finished process and every stub call in order.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        utils_dir = root / "scripts" / "tests" / "deploy" / "swarm" / "utils"
        (utils_dir / "clean").mkdir(parents=True)
        (utils_dir / "release.sh").symlink_to(RELEASE)
        act_dir = root / "scripts" / "tests" / "deploy" / "act"
        act_dir.mkdir(parents=True)
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for path, body in (
            (utils_dir / "clean" / "teardown.sh", TEARDOWN_STUB),
            (act_dir / "down_act_outer.sh", DOWN_ACT_STUB),
            (bin_dir / "docker", DOCKER_STUB),
        ):
            path.write_text(body)
            path.chmod(0o755)
        log = Path(tmp) / "calls.log"
        log.touch()
        env = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_CP_ERROR=cp_error,
            SWARM_NAME="web-app-demo",
            keep=keep,
            INFINITO_CONTAINER="own",
            INFINITO_RESCUE_DIAGNOSTICS_BASE=str(Path(tmp) / "rescue"),
        )
        done = subprocess.run(
            [
                "bash",
                str(utils_dir / "release.sh"),
                "bash",
                "-c",
                f'echo drill >>"{log}"; exit {drill_rc}',
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log


class TestReleaseAfterRescue(unittest.TestCase):
    def test_a_green_drill_saves_then_releases(self) -> None:
        done, calls = release("", 0)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls[0], "drill")
        self.assertTrue(calls[2].startswith("docker cp act-id:"), calls)
        self.assertEqual(calls[-2], "teardown SWARM_NAME=web-app-demo KEEP=false")
        self.assertEqual(calls[-1], "down_act_outer")

    def test_a_failed_drill_releases_too_and_keeps_its_exit_code(self) -> None:
        done, calls = release("false", 3)
        self.assertEqual(done.returncode, 3)
        self.assertIn("teardown SWARM_NAME=web-app-demo KEEP=false", calls)
        self.assertEqual(calls[-1], "down_act_outer")

    def test_the_rescue_bundle_is_copied_before_anything_is_removed(self) -> None:
        _, calls = release("", 1)
        copies = [i for i, call in enumerate(calls) if call.startswith("docker cp ")]
        self.assertEqual(len(copies), 2, calls)
        self.assertLess(
            max(copies), calls.index(next(c for c in calls if c.startswith("teardown")))
        )

    def test_keep_true_saves_but_leaves_the_cluster_up(self) -> None:
        done, calls = release("true", 1)
        self.assertEqual(done.returncode, 1)
        self.assertTrue(any(call.startswith("docker cp ") for call in calls))
        self.assertFalse([call for call in calls if call.startswith("teardown")])
        self.assertNotIn("down_act_outer", calls)

    def test_an_absent_bundle_does_not_stop_the_release(self) -> None:
        done, calls = release(
            "", 0, cp_error="Error: No such container:path: act-id:/tmp/x"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls[-1], "down_act_outer")

    def test_a_failed_copy_keeps_the_act_container_and_fails(self) -> None:
        done, calls = release("", 0, cp_error="no space left on device")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("teardown SWARM_NAME=web-app-demo KEEP=false", calls)
        self.assertNotIn("down_act_outer", calls)
        self.assertIn("make swarm-down name=web-app-demo", done.stderr)

    def test_an_unknown_keep_value_runs_nothing(self) -> None:
        done, calls = release("yes", 0)
        self.assertEqual(done.returncode, 2)
        self.assertEqual(calls, [])


class TestSwarmZombieWiring(unittest.TestCase):
    def setUp(self) -> None:
        text = read_text(str(MAKEFILE))
        self.recipe = re.search(
            r"^swarm-zombie:.*?(?=^\.PHONY)", text, re.DOTALL | re.MULTILINE
        )[0]

    def test_the_drill_runs_inside_release(self) -> None:
        self.assertIn(
            "bash scripts/tests/deploy/swarm/utils/release.sh bash scripts/tests/deploy/act/workflow.sh",
            self.recipe,
        )

    def test_an_env_without_the_cache_keys_still_starts_the_drill(self) -> None:
        for key in (
            "INFINITO_CACHE_SHARED_HOST_PATH",
            "INFINITO_CACHE_HOST_PACMAN_PATH",
        ):
            self.assertIn(f"{key}=$${{{key}:-}};", self.recipe)

    def test_keep_decides_whether_the_act_job_keeps_the_nodes(self) -> None:
        self.assertIn("keep='$(keep)'", self.recipe)
        self.assertIn(
            "INFINITO_KEEP_SWARM_NODES=$(if $(filter true,$(keep)),true,false)",
            self.recipe,
        )


if __name__ == "__main__":
    unittest.main()
