from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "scripts" / "image" / "build.sh"

DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_LOG}"
if [ "$1 $2" = "image inspect" ]; then
\texit 1
fi
if [ "$1 $2 $3" = "builder prune --help" ]; then
\tprintf '%s\\n' "${STUB_PRUNE_HELP}"
fi
"""

MAX_USED = "      --max-used-space bytes   Maximum amount of disk space allowed to keep for cache"
KEEP_STORAGE = "      --keep-storage bytes     Amount of disk space to keep for cache"
NEITHER = "  -a, --all   Remove all unused build cache, not just dangling ones"


def _build(prune_help: str, cap: str) -> tuple[int, list[str], str]:
    """Args:
        prune_help: what `docker builder prune --help` prints on the stubbed engine.
        cap: the INFINITO_BUILD_CACHE_MAX_SIZE of the build.

    Returns:
        The exit code, every docker call and the combined output.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "docker"
        stub.write_text(DOCKER_STUB)
        stub.chmod(0o755)
        log = Path(tmp) / "calls"
        env = dict(os.environ)
        env.update(
            {
                "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                "HOME": tmp,
                "STUB_LOG": str(log),
                "STUB_PRUNE_HELP": prune_help,
                "INFINITO_DISTRO": "debian",
                "INFINITO_PARENT_IMAGE": "debian:stable",
                "INFINITO_IMAGE_REPOSITORY": "probe",
                "INFINITO_SRC_DIR": "/opt/src/infinito",
                "INFINITO_VENV_DIR": "/opt/venvs/infinito",
                "INFINITO_PACKAGE_INSTALL_SCRIPT": "package.sh",
                "INFINITO_PYTHON_INSTALL_SCRIPT": "python.sh",
                "INFINITO_DOCKER_CLI_INSTALL_SCRIPT": "docker-cli.sh",
                "INFINITO_BUILD_CACHE_MAX_SIZE": cap,
                "GITHUB_REPOSITORY_OWNER": "probe-owner",
            }
        )
        for key in ("GITHUB_REPOSITORY", "OWNER"):
            env.pop(key, None)
        done = subprocess.run(
            ["bash", str(SCRIPT), "--tag", "probe/debian:dev-1"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = read_text(str(log)).splitlines() if log.exists() else []
    return done.returncode, calls, done.stdout + done.stderr


class TestBuildCachePrune(unittest.TestCase):
    def test_a_build_ends_with_a_prune_down_to_the_cap(self) -> None:
        code, calls, _ = _build(MAX_USED, "20g")
        self.assertEqual(code, 0)
        builds = [i for i, call in enumerate(calls) if call.startswith("build ")]
        self.assertEqual(len(builds), 1)
        self.assertEqual(calls[-1], "builder prune --force --max-used-space 20g")
        self.assertGreater(len(calls) - 1, builds[0])

    def test_an_older_engine_prunes_with_keep_storage(self) -> None:
        code, calls, _ = _build(KEEP_STORAGE, "20g")
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], "builder prune --force --keep-storage 20g")

    def test_the_prune_follows_the_cap(self) -> None:
        _, calls, _ = _build(MAX_USED, "7g")
        self.assertEqual(calls[-1], "builder prune --force --max-used-space 7g")

    def test_an_engine_without_a_keep_flag_fails_the_build_loudly(self) -> None:
        code, calls, output = _build(NEITHER, "20g")
        self.assertNotEqual(code, 0)
        self.assertFalse(
            any(call.startswith("builder prune --force") for call in calls)
        )
        self.assertIn("--max-used-space", output)
        self.assertIn("--keep-storage", output)
        self.assertIn("INFINITO_BUILD_CACHE_MAX_SIZE", output)


if __name__ == "__main__":
    unittest.main()
