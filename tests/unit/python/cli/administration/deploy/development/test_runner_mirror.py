from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development import runner_mirror
from cli.administration.deploy.development.env import compose_file_args
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.docker.image.pin import SEMVER, pin_class
from utils.env.parser import parse_static_env

INIT_IMAGE = "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE"
LOCAL_IMAGE = "registry.example/local-init:1.0"

GITHUB = {
    "GITHUB_REPOSITORY_OWNER": "Acme",
    "GITHUB_REPOSITORY": "Acme/Core",
    "INFINITO_GHCR_MIRROR_PREFIX": "mirror",
}

COMPOSE = """\
services:
  coredns:
    image: coredns/coredns:1.14.4
"""

CACHE_OVERRIDE = """\
services:
  package-cache-frontend:
    image: nginx:1.27-alpine
"""


def _repo(root: Path) -> Path:
    (root / "compose").mkdir()
    (root / "compose.yml").write_text(COMPOSE)
    (root / "compose" / "cache.override.yml").write_text(CACHE_OVERRIDE)
    (root / "default.env").write_text(
        "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE=alpine:latest\n"
    )
    return root


class TestRunnerMirror(unittest.TestCase):
    @patch.dict(os.environ, GITHUB, clear=False)
    def test_the_override_covers_only_services_of_layered_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            relative = runner_mirror.write_override(root, ["compose.yml"])
            written = load_yaml_any(str(root / relative), default_if_missing={})
        self.assertEqual(
            written,
            {
                "services": {
                    "coredns": {
                        "image": "ghcr.io/acme/core/mirror/docker.io/coredns/coredns:1.14.4"
                    }
                }
            },
        )

    @patch.dict(os.environ, {**GITHUB, "INFINITO_GHCR_MIRROR": "true"}, clear=False)
    def test_the_declared_init_image_resolves_to_a_pinned_mirror_tag(self) -> None:
        name, _, tag = runner_mirror.mirror_image(PROJECT_ROOT, INIT_IMAGE).rpartition(
            ":"
        )
        self.assertEqual(name, "ghcr.io/acme/core/mirror/docker.io/alpine")
        self.assertEqual(pin_class(tag), SEMVER)

    def test_the_cli_prints_the_mirror_only_while_the_mirror_is_on(self) -> None:
        declared = parse_static_env(PROJECT_ROOT / "default.env")[INIT_IMAGE]
        for mirror, expected in (
            ("true", f"ghcr.io/acme/core/mirror/docker.io/{declared}"),
            ("false", ""),
        ):
            with self.subTest(mirror=mirror):
                done = subprocess.run(
                    [sys.executable, "-m", runner_mirror.__name__, INIT_IMAGE],
                    cwd=PROJECT_ROOT,
                    env={
                        **os.environ,
                        **GITHUB,
                        "INFINITO_GHCR_MIRROR": mirror,
                        INIT_IMAGE: LOCAL_IMAGE,
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stdout.strip(), expected)

    @patch.dict(
        os.environ,
        {
            **GITHUB,
            "INFINITO_RUNNING_ON_GITHUB": "true",
            "INFINITO_GIT_COMMON_DIR": "",
            "INFINITO_CACHE_STACK": "",
            "INFINITO_GHCR_MIRROR": "",
            "INFINITO_PUBLISH_PORTS": "",
            "INFINITO_GPU_COUNT": "0",
        },
        clear=False,
    )
    def test_a_github_runner_layers_the_mirror_override_last(self) -> None:
        with patch.object(
            runner_mirror, "write_override", return_value=runner_mirror.OVERRIDE
        ) as write:
            args = compose_file_args()
        write.assert_called_once_with(PROJECT_ROOT, ["compose.yml"])
        self.assertEqual(args[-2:], ["-f", runner_mirror.OVERRIDE])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
