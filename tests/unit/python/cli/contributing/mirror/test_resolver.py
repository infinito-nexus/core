from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import cli.contributing.mirror.resolver.__main__ as resolver_main
from cli.contributing.mirror.model import ImageRef
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class TestResolverOutputFormat(unittest.TestCase):
    """resolver emits per-role services map under the applications key."""

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
            patch(
                "cli.contributing.mirror.resolver.__main__.iter_role_images",
                return_value=images,
            ),
            patch("sys.argv", argv),
            patch("sys.stdout", buf),
        ):
            result = resolver_main.main()

        self.assertEqual(result, 0)
        return load_yaml_str(buf.getvalue()) or {}

    def test_meta_services_image_goes_to_applications_key(self) -> None:
        image = ImageRef(
            role="web-app-nextcloud",
            service="app",
            name="nextcloud",
            version="31.0.0",
            source="docker.io/library/nextcloud:31.0.0",
            registry="docker.io",
            source_file=ROLE_FILE_META_SERVICES,
        )
        out = self._run_resolver([image])

        self.assertIn("applications", out)
        self.assertNotIn("images", out)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc["version"], "31.0.0")
        self.assertIn("ghcr.io/acme/myrepo/mirror/docker.io/nextcloud", svc["image"])

    def test_test_role_image_also_goes_to_applications_key(self) -> None:
        image = ImageRef(
            role="test-e2e-playwright",
            service="playwright",
            name="playwright",
            version="v1.58.2-noble",
            source="mcr.microsoft.com/playwright:v1.58.2-noble",
            registry="mcr.microsoft.com",
            source_file=ROLE_FILE_META_SERVICES,
        )
        out = self._run_resolver([image])

        svc = out["applications"]["test-e2e-playwright"]["services"]["playwright"]
        self.assertEqual(svc["version"], "v1.58.2-noble")
        self.assertIn(
            "ghcr.io/acme/myrepo/mirror/mcr.microsoft.com/playwright",
            svc["image"],
        )

    def test_multiple_services_same_role_stay_grouped(self) -> None:
        images = [
            ImageRef(
                role="web-app-nextcloud",
                service="app",
                name="nextcloud",
                version="31.0.0",
                source="docker.io/library/nextcloud:31.0.0",
                registry="docker.io",
                source_file=ROLE_FILE_META_SERVICES,
            ),
            ImageRef(
                role="web-app-nextcloud",
                service="proxy",
                name="nginx",
                version="alpine",
                source="docker.io/library/nginx:alpine",
                registry="docker.io",
                source_file=ROLE_FILE_META_SERVICES,
            ),
        ]
        out = self._run_resolver(images)

        self.assertIn("app", out["applications"]["web-app-nextcloud"]["services"])
        self.assertIn("proxy", out["applications"]["web-app-nextcloud"]["services"])

    def test_empty_images_yield_empty_applications(self) -> None:
        out = self._run_resolver([])
        self.assertEqual(out["applications"], {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
