from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.env.handlers.infinito.cache import registries

SERVICES = {
    "web-app-a": "app:\n  image: ghcr.io/foo/a\n  version: 1\n",
    "web-app-b": "app:\n  image: quay.io/foo/b\nhub:\n  image: docker.io/library/nginx\n",
    "web-app-c": 'app:\n  image: nginx\n  sidecar:\n    image: "mcr.microsoft.com/foo"\n',
    "web-app-d": 'app:\n  image: "{{ IMAGE }}"\n',
}


class TestImageRegistries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for role, text in SERVICES.items():
            meta = root / "roles" / role / "meta"
            meta.mkdir(parents=True)
            (meta / "services.yml").write_text(text)
        patcher = patch.object(registries, "PROJECT_ROOT", root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_every_vendor_registry_a_role_image_names_is_listed(self):
        self.assertEqual(
            registries.image_registries(),
            ["ghcr.io", "mcr.microsoft.com", "quay.io"],
        )

    def test_the_proxy_list_adds_the_base_registries_on_top(self):
        self.assertEqual(
            registries.declared_registries(),
            sorted({"ghcr.io", "mcr.microsoft.com", "quay.io"} | registries.BASE),
        )

    def test_the_base_registries_are_not_vendors_of_the_role_images(self):
        self.assertEqual(set(registries.image_registries()) & registries.BASE, set())


if __name__ == "__main__":
    unittest.main()
