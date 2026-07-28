"""Contract of the CI environment image resolver.

``scripts/meta/resolve/image/ci.sh`` is what every deploy mode calls to pin the
distro it is currently on to a prebuilt image, so the reference it prints is
pinned against ``utils.distros.environment_image`` for every declared distro: a
locally re-spelled ``ghcr.io/...`` would silently address a different image.
The absent-owner case prints nothing, which is the caller's signal to build
locally, and a missing distro or tag aborts instead of rendering a hole.
"""

from __future__ import annotations

import os
import subprocess
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.distros import distro_names, environment_image

RESOLVER = PROJECT_ROOT / "scripts" / "meta" / "resolve" / "image" / "ci.sh"
STRIPPED = (
    "OWNER",
    "GITHUB_REPOSITORY_OWNER",
    "GITHUB_REPOSITORY",
    "REPO_PREFIX",
    "INFINITO_DISTRO",
    "INFINITO_IMAGE_REPOSITORY",
    "INFINITO_IMAGE_TAG",
)
TAG = "ci-abc123"


class TestResolveCiImage(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
        env["BASH_ENV"] = ""
        env.update(overrides)
        return env

    def _run(self, script: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [script],
            cwd=PROJECT_ROOT,
            env=self._env(**env),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_every_distro_renders_the_spot_template(self) -> None:
        for distro in distro_names():
            with self.subTest(distro=distro):
                proc = self._run(
                    str(RESOLVER),
                    OWNER="acme",
                    INFINITO_DISTRO=distro,
                    INFINITO_IMAGE_REPOSITORY="infinito-nexus-core",
                    INFINITO_IMAGE_TAG=TAG,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(
                    proc.stdout.strip(),
                    environment_image(
                        distro,
                        owner="acme",
                        repository="infinito-nexus-core",
                        tag=TAG,
                    ),
                )

    def test_repository_is_delegated_to_the_name_resolver(self) -> None:
        proc = self._run(
            str(RESOLVER),
            OWNER="acme",
            REPO_PREFIX="delegated-repo",
            INFINITO_DISTRO="debian",
            INFINITO_IMAGE_TAG=TAG,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout.strip(),
            environment_image(
                "debian",
                owner="acme",
                repository="delegated-repo",
                tag=TAG,
            ),
        )

    def test_no_registry_owner_in_scope_prints_nothing(self) -> None:
        proc = self._run(
            str(RESOLVER),
            INFINITO_DISTRO="debian",
            INFINITO_IMAGE_TAG=TAG,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_missing_distro_is_a_hard_error(self) -> None:
        proc = self._run(str(RESOLVER), OWNER="acme", INFINITO_IMAGE_TAG=TAG)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("INFINITO_DISTRO", proc.stderr)

    def test_missing_tag_is_a_hard_error(self) -> None:
        proc = self._run(str(RESOLVER), OWNER="acme", INFINITO_DISTRO="debian")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("INFINITO_IMAGE_TAG", proc.stderr)


if __name__ == "__main__":
    unittest.main()
