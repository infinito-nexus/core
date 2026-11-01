import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts/image/build.sh"

DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_LOG}"
if [ "$1 $2" = "image inspect" ]; then
\texit 1
fi
"""


class TestImageBuildLabels(unittest.TestCase):
    def run_build(self, *args):
        """Run build.sh against a stubbed docker CLI in an empty build context.

        Args:
            args: the arguments build.sh receives.

        Returns:
            Tuple of the exit code and every docker call, one string each.
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
                    "INFINITO_DISTRO": "debian",
                    "INFINITO_PARENT_IMAGE": "debian:stable",
                    "INFINITO_IMAGE_REPOSITORY": "probe",
                    "INFINITO_SRC_DIR": "/opt/src/infinito",
                    "INFINITO_VENV_DIR": "/opt/venvs/infinito",
                    "INFINITO_PACKAGE_INSTALL_SCRIPT": "package.sh",
                    "INFINITO_PYTHON_INSTALL_SCRIPT": "python.sh",
                    "INFINITO_DOCKER_CLI_INSTALL_SCRIPT": "docker-cli.sh",
                }
            )
            for key in ("GITHUB_REPOSITORY", "GITHUB_REPOSITORY_OWNER", "OWNER"):
                env.pop(key, None)
            done = subprocess.run(
                ["bash", str(SCRIPT), *args],
                cwd=tmp,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            calls = log.read_text().splitlines() if log.exists() else []
        return done.returncode, calls

    def test_every_label_reaches_the_local_build(self):
        rc, calls = self.run_build(
            "--missing",
            "--tag",
            "probe/debian:dev-1",
            "--label",
            "nexus.infinito.prune=keep",
            "--label",
            "nexus.infinito.role=semaphore",
        )
        self.assertEqual(rc, 0)
        builds = [call for call in calls if call.startswith("build ")]
        self.assertEqual(len(builds), 1)
        self.assertIn("--label nexus.infinito.prune=keep", builds[0])
        self.assertIn("--label nexus.infinito.role=semaphore", builds[0])
        self.assertIn("-t probe/debian:dev-1", builds[0])

    def test_a_build_without_labels_passes_none(self):
        rc, calls = self.run_build("--tag", "probe/debian:dev-1")
        self.assertEqual(rc, 0)
        builds = [call for call in calls if call.startswith("build ")]
        self.assertEqual(len(builds), 1)
        self.assertNotIn("--label", builds[0])

    def test_a_label_without_a_value_is_refused_before_any_docker_call(self):
        rc, calls = self.run_build("--label", "nexus.infinito.prune")
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
