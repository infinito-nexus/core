from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.docker.image.discovery import iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES

BASE = """---
engine:
  image: libretranslate/libretranslate
  version: v1.9.6
"""

WITH_VARIANTS = """---
engine:
  image: libretranslate/libretranslate
  version: v1.9.6
  version_variants:
    - "-cuda"
"""


class TestImageDiscoveryVersionVariants(unittest.TestCase):
    def _versions(self, services_yaml: str) -> set[str]:
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "roles" / "svc-demo" / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(services_yaml, encoding="utf-8")
            return {ref.version for ref in iter_role_images(Path(tmp))}

    def test_a_role_without_variants_yields_only_the_declared_version(self) -> None:
        self.assertEqual({"v1.9.6"}, self._versions(BASE))

    def test_each_variant_suffix_yields_its_own_ref(self) -> None:
        self.assertEqual({"v1.9.6", "v1.9.6-cuda"}, self._versions(WITH_VARIANTS))

    def test_the_variant_ref_carries_the_derived_pull_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "roles" / "svc-demo" / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(WITH_VARIANTS, encoding="utf-8")
            sources = {ref.source for ref in iter_role_images(Path(tmp))}

        self.assertIn("docker.io/libretranslate/libretranslate:v1.9.6-cuda", sources)

    def test_only_the_variant_ref_is_marked_derived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "roles" / "svc-demo" / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(WITH_VARIANTS, encoding="utf-8")
            derived = {ref.version: ref.derived for ref in iter_role_images(Path(tmp))}

        self.assertEqual({"v1.9.6": False, "v1.9.6-cuda": True}, derived)

    def test_blank_and_non_list_variants_are_ignored(self) -> None:
        for declaration in (
            '  version_variants: "-cuda"\n',
            "  version_variants:\n    - '   '\n",
        ):
            with self.subTest(declaration=declaration):
                self.assertEqual({"v1.9.6"}, self._versions(BASE + declaration))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
