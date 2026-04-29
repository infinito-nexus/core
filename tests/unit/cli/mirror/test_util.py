from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.docker.image.discovery import iter_role_images


def _make_fs(files: dict[str, str]) -> dict[Path, str]:
    return {Path(k): textwrap.dedent(v) for k, v in files.items()}


class TestIterRoleImagesVarsImages(unittest.TestCase):
    """iter_role_images reads defaults/main.yml → images and meta/services.yml → services (any registry)."""

    def _run(self, fs: dict[str, str]) -> list:
        real_fs = _make_fs(fs)

        def fake_glob(self, pattern: str):
            return [p for p in real_fs if p.match(pattern)]

        def fake_load(path: Path) -> dict:
            import yaml

            content = real_fs.get(path, "")
            return yaml.safe_load(content) or {}

        with (
            patch.object(Path, "glob", fake_glob),
            patch("utils.docker.image.discovery.load_yaml", side_effect=fake_load),
        ):
            return list(iter_role_images(Path("/repo")))

    def test_mcr_playwright_image(self):
        refs = self._run(
            {
                "roles/test-e2e-playwright/defaults/main.yml": """
                images:
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
        self.assertEqual(ref.source_file, "defaults/main.yml")

    def test_ghcr_image_strips_registry_from_name(self):
        refs = self._run(
            {
                "roles/web-app-matrix/defaults/main.yml": """
                images:
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
        self.assertEqual(ref.source_file, "defaults/main.yml")

    def test_missing_image_or_version_is_skipped(self):
        refs = self._run(
            {
                "roles/some-role/defaults/main.yml": """
                images:
                  no-version:
                    image: ghcr.io/foo/bar
                  no-image:
                    version: "1.0"
            """,
            }
        )
        self.assertEqual(refs, [])

    def test_no_images_key_yields_nothing(self):
        refs = self._run(
            {
                "roles/some-role/defaults/main.yml": """
                some_var: value
            """,
            }
        )
        self.assertEqual(refs, [])

    def test_config_main_yml_ghcr_image(self):
        # Per req-008 the file root IS the services map (no compose envelope)
        # and source_file reports the new path.
        refs = self._run(
            {
                "roles/web-app-matrix/meta/services.yml": """
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
        self.assertEqual(ref.source_file, "meta/services.yml")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
