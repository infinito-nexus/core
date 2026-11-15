from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.deploy.development import runner_mirror
from cli.administration.deploy.development.env import compose_file_args
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

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

    def test_no_env_image_helper_is_left(self) -> None:
        self.assertFalse(hasattr(runner_mirror, "env_image"))

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
