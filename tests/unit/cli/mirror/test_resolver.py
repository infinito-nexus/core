from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import yaml

import cli.mirror.resolver.__main__ as resolver_main
from cli.mirror.model import ImageRef


class TestResolverOutputFormat(unittest.TestCase):
    """resolver emits per-role services map and a separate images key."""

    def _run_resolver(
        self, images: list[ImageRef], extra_argv: list[str] | None = None
    ) -> dict:
        argv = [
            "resolver",
            "--ghcr-namespace",
            "acme",
            "--ghcr-repository",
            "myrepo",
        ]
        if extra_argv:
            argv += extra_argv

        buf = io.StringIO()
        with (
            patch("cli.mirror.resolver.__main__.iter_role_images", return_value=images),
            patch("sys.argv", argv),
            patch("sys.stdout", buf),
        ):
            result = resolver_main.main()

        self.assertEqual(result, 0)
        return yaml.safe_load(buf.getvalue()) or {}

    def test_compose_images_go_to_applications_key(self) -> None:
        image = ImageRef(
            role="web-app-nextcloud",
            service="app",
            name="nextcloud",
            version="31.0.0",
            source="docker.io/library/nextcloud:31.0.0",
            registry="docker.io",
            source_file="meta/services.yml",
        )
        out = self._run_resolver([image])

        self.assertIn("applications", out)
        self.assertIn("images", out)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc["version"], "31.0.0")
        self.assertIn("ghcr.io/acme/myrepo/mirror/docker.io/nextcloud", svc["image"])
        self.assertEqual(out["images"], {})

    def test_defaults_images_go_to_images_key(self) -> None:
        image = ImageRef(
            role="test-e2e-playwright",
            service="playwright",
            name="playwright",
            version="v1.58.2-noble",
            source="mcr.microsoft.com/playwright:v1.58.2-noble",
            registry="mcr.microsoft.com",
            source_file="defaults/main.yml",
        )
        out = self._run_resolver([image])

        self.assertEqual(out["applications"], {})
        svc = out["images"]["test-e2e-playwright"]["playwright"]
        self.assertEqual(svc["version"], "v1.58.2-noble")
        self.assertIn(
            "ghcr.io/acme/myrepo/mirror/mcr.microsoft.com/playwright",
            svc["image"],
        )

    def test_multiple_services_same_role_stay_grouped_per_source_type(self) -> None:
        images = [
            ImageRef(
                role="web-app-nextcloud",
                service="app",
                name="nextcloud",
                version="31.0.0",
                source="docker.io/library/nextcloud:31.0.0",
                registry="docker.io",
                source_file="meta/services.yml",
            ),
            ImageRef(
                role="web-app-nextcloud",
                service="proxy",
                name="nginx",
                version="alpine",
                source="docker.io/library/nginx:alpine",
                registry="docker.io",
                source_file="meta/services.yml",
            ),
            ImageRef(
                role="web-app-nextcloud",
                service="backup",
                name="restic",
                version="latest",
                source="docker.io/restic/restic:latest",
                registry="docker.io",
                source_file="defaults/main.yml",
            ),
        ]
        out = self._run_resolver(images)

        self.assertIn("app", out["applications"]["web-app-nextcloud"]["services"])
        self.assertIn("proxy", out["applications"]["web-app-nextcloud"]["services"])
        self.assertIn("backup", out["images"]["web-app-nextcloud"])

    def test_empty_images_yield_both_empty_top_level_keys(self) -> None:
        out = self._run_resolver([])
        self.assertEqual(out["applications"], {})
        self.assertEqual(out["images"], {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
