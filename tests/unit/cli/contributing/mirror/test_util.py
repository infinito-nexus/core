from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.yaml import load_yaml_str
from utils.docker.image.discovery import iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES


def _make_fs(files: dict[str, str]) -> dict[Path, str]:
    return {Path(k): textwrap.dedent(v) for k, v in files.items()}


class TestIterRoleImagesMetaServices(unittest.TestCase):
    """iter_role_images reads meta/services.yml → services (any registry)."""

    def _run(self, fs: dict[str, str]) -> list:
        real_fs = _make_fs(fs)

        def fake_glob(self, pattern: str):
            return [p for p in real_fs if p.match(pattern)]

        def fake_load(path: Path) -> dict:

            content = real_fs.get(path, "")
            return load_yaml_str(content) or {}

        with (
            patch.object(Path, "glob", fake_glob),
            patch("utils.docker.image.discovery.load_yaml", side_effect=fake_load),
        ):
            return list(iter_role_images(Path("/repo")))

    def test_mcr_playwright_image(self):
        refs = self._run(
            {
                f"roles/test-e2e-playwright/{ROLE_FILE_META_SERVICES}": """
                playwright:
                  image: mcr.microsoft.com/playwright
                  version: v1.58.2-noble
            """,
            }
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref.role, "test-e2e-playwright")
        self.assertEqual(ref.service, "playwright")
        self.assertEqual(ref.name, "playwright")
        self.assertEqual(ref.version, "v1.58.2-noble")
        self.assertEqual(ref.registry, "mcr.microsoft.com")
        self.assertEqual(ref.source, "mcr.microsoft.com/playwright:v1.58.2-noble")
        self.assertEqual(ref.source_file, ROLE_FILE_META_SERVICES)

    def test_ghcr_image_strips_registry_from_name(self):
        refs = self._run(
            {
                f"roles/web-app-matrix/{ROLE_FILE_META_SERVICES}": """
                matrix-chatgpt-bot:
                  image: ghcr.io/matrixgpt/matrix-chatgpt-bot
                  version: latest
            """,
            }
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref.name, "matrixgpt/matrix-chatgpt-bot")
        self.assertEqual(ref.registry, "ghcr.io")
        self.assertEqual(ref.source, "ghcr.io/matrixgpt/matrix-chatgpt-bot:latest")
        self.assertEqual(ref.source_file, ROLE_FILE_META_SERVICES)

    def test_missing_image_or_version_is_skipped(self):
        refs = self._run(
            {
                f"roles/some-role/{ROLE_FILE_META_SERVICES}": """
                no-version:
                  image: ghcr.io/foo/bar
                no-image:
                  version: "1.0"
            """,
            }
        )
        self.assertEqual(refs, [])

    def test_no_image_keys_yields_nothing(self):
        refs = self._run(
            {
                f"roles/some-role/{ROLE_FILE_META_SERVICES}": """
                some-svc:
                  lifecycle: beta
            """,
            }
        )
        self.assertEqual(refs, [])

    def test_meta_services_ghcr_image(self):
        refs = self._run(
            {
                f"roles/web-app-matrix/{ROLE_FILE_META_SERVICES}": """
                matrix-chatgpt-bot:
                  image: ghcr.io/matrixgpt/matrix-chatgpt-bot
                  version: latest
            """,
            }
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref.role, "web-app-matrix")
        self.assertEqual(ref.service, "matrix-chatgpt-bot")
        self.assertEqual(ref.name, "matrixgpt/matrix-chatgpt-bot")
        self.assertEqual(ref.registry, "ghcr.io")
        self.assertEqual(ref.source, "ghcr.io/matrixgpt/matrix-chatgpt-bot:latest")
        self.assertEqual(ref.source_file, ROLE_FILE_META_SERVICES)

    def test_gitlab_registry_image_strips_registry_from_name(self):
        refs = self._run(
            {
                f"roles/web-app-gitlab/{ROLE_FILE_META_SERVICES}": """
                webservice:
                  image: registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ce
                  version: v19.1.1
            """,
            }
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref.role, "web-app-gitlab")
        self.assertEqual(ref.service, "webservice")
        self.assertEqual(ref.name, "gitlab-org/build/cng/gitlab-webservice-ce")
        self.assertEqual(ref.registry, "registry.gitlab.com")
        self.assertEqual(
            ref.source,
            "registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ce:v19.1.1",
        )
        self.assertEqual(ref.source_file, ROLE_FILE_META_SERVICES)

    def test_opencode_gitlab_image_strips_registry_from_name(self):
        refs = self._run(
            {
                f"roles/web-app-opentalk/{ROLE_FILE_META_SERVICES}": """
                controller:
                  image: registry.opencode.de/opentalk/controller
                  version: v0.33.2
            """,
            }
        )
        self.assertEqual(len(refs), 1)
        ref = refs[0]
        self.assertEqual(ref.role, "web-app-opentalk")
        self.assertEqual(ref.service, "controller")
        self.assertEqual(ref.name, "opentalk/controller")
        self.assertEqual(ref.registry, "registry.opencode.de")
        self.assertEqual(ref.source, "registry.opencode.de/opentalk/controller:v0.33.2")
        self.assertEqual(ref.source_file, ROLE_FILE_META_SERVICES)


if __name__ == "__main__":
    unittest.main()
