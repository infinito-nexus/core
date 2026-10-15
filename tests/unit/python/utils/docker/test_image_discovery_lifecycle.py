from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from utils.docker.image.discovery import iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SUPPORTED = """---
demo:
  image: libretranslate/libretranslate
  version: v1.9.6
  lifecycle: stable
helper:
  image: alpine
  version: "3.22"
"""

RETIRED = """---
demo:
  image: quay.io/minio/minio
  version: RELEASE.2025-09-07T16-13-09Z
  lifecycle: eol
client:
  image: quay.io/minio/mc
  version: RELEASE.2025-08-13T08-35-41Z
"""

UNSTAGED = """---
demo:
  image: libretranslate/libretranslate
  version: v1.9.6
"""


class TestImageDiscoveryLifecycle(unittest.TestCase):
    def _images(self, services_yaml: str, *, relative: bool = False) -> set[str]:
        """Discover the images of one role written into a temporary repository.

        Args:
            services_yaml: the role's ``meta/services.yml``.
            relative: pass the repository root relative to the working directory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            services = Path(tmp) / "roles" / "web-app-demo" / ROLE_FILE_META_SERVICES
            services.parent.mkdir(parents=True)
            services.write_text(services_yaml, encoding="utf-8")
            root = Path(os.path.relpath(tmp)) if relative else Path(tmp)
            return {ref.service for ref in iter_role_images(root)}

    def test_a_supported_role_yields_every_service(self) -> None:
        self.assertEqual({"demo", "helper"}, self._images(SUPPORTED))

    def test_a_retired_role_yields_none_of_its_services(self) -> None:
        self.assertEqual(set(), self._images(RETIRED))

    def test_a_role_that_names_no_stage_is_kept(self) -> None:
        self.assertEqual({"demo"}, self._images(UNSTAGED))

    def test_a_relative_root_still_leaves_a_retired_role_out(self) -> None:
        self.assertEqual(set(), self._images(RETIRED, relative=True))


if __name__ == "__main__":
    unittest.main()
