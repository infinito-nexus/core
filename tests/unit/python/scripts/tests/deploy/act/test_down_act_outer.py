from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "tests" / "deploy" / "act" / "down_act_outer.sh"
DOCKER_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'if [ "$1" = ps ]; then\n'
    '  case "$*" in *"label=infinito.worktree=own"*) echo own-id ;; esac\n'
    "fi\n"
)


def teardown(container: str | None) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the teardown against a ``docker`` stub that only knows ``own-id``.

    Args:
        container: value of ``INFINITO_CONTAINER``, or None to leave it unset.

    Returns:
        The finished process and the docker invocations it made.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "docker"
        stub.write_text(DOCKER_STUB)
        stub.chmod(0o755)
        log = Path(tmp) / "docker.log"
        log.touch()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("BASH_ENV", "INFINITO_CONTAINER")
        }
        env.update(PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}", STUB_LOG=str(log))
        if container is not None:
            env["INFINITO_CONTAINER"] = container
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()  # nocheck: cache-read  stub call log


class TestDownActOuter(unittest.TestCase):
    def test_only_the_own_worktrees_act_containers_are_listed(self) -> None:
        _, calls = teardown("own")
        self.assertIn("label=infinito.worktree=own", calls[0])

    def test_the_own_act_container_is_removed(self) -> None:
        _, calls = teardown("own")
        self.assertEqual(calls[1], "rm -f own-id")

    def test_a_foreign_worktrees_act_container_is_left_alone(self) -> None:
        _, calls = teardown("foreign")
        self.assertEqual(len(calls), 1)

    def test_an_unset_container_name_removes_nothing(self) -> None:
        done, calls = teardown(None)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
