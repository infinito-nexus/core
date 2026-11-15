from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from tests.external.update.docker import test_image_pin_policy as pin_policy
from tests.external.update.docker import test_image_reachable as reachable
from utils.roles.custom import MARKER_FILE, MARKER_HEADER
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = "web-app-cst-store"
IMAGE = "ghcr.io/infinito-nexus/store"
VERSION = "0.3.4"
LOOKUP = f'{{{{ lookup("role_version", "{ROLE}") }}}}'
SERVICES = f"""---
store:
  image: {IMAGE}
  version: 'v{LOOKUP}'
store-full:
  image: {IMAGE}
  version: 'full-v{LOOKUP}'
"""
RESOLVED = {f"v{VERSION}", f"full-v{VERSION}"}


class TestRoleVersionPins(unittest.TestCase):
    def _repo(self, version: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        role = Path(tmp.name) / "roles" / ROLE
        services = role / ROLE_FILE_META_SERVICES
        services.parent.mkdir(parents=True)
        services.write_text(SERVICES, encoding="utf-8")
        fields = [MARKER_HEADER, f"directory: {ROLE}"]
        if version:
            fields.append(f"version: {version}")
        (role / MARKER_FILE).write_text("\n".join(fields) + "\n", encoding="utf-8")
        return Path(tmp.name)

    def _pin_policy(self, root: Path) -> None:
        with mock.patch.object(pin_policy, "PROJECT_ROOT", root):
            pin_policy.TestImagePinPolicy(
                "test_unpinned_and_unversioned_entries_are_rejected"
            ).test_unpinned_and_unversioned_entries_are_rejected()

    def _registry_requests(self, root: Path) -> set[tuple[str, str]]:
        asked: set[tuple[str, str]] = set()

        def exists(image: str, version: str) -> bool:
            asked.add((image, version))
            return version in RESOLVED

        with (
            mock.patch.object(reachable, "PROJECT_ROOT", root),
            mock.patch.object(reachable, "manifest_exists", exists),
            mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "1"}),
        ):
            reachable.TestDockerImageReachable(
                "test_pinned_images_are_reachable"
            ).test_pinned_images_are_reachable()
        return asked

    def test_the_pin_policy_accepts_the_pulled_version(self) -> None:
        self._pin_policy(self._repo(VERSION))

    def test_the_registry_is_asked_for_the_pulled_version(self) -> None:
        self.assertEqual(
            {(IMAGE, tag) for tag in RESOLVED},
            self._registry_requests(self._repo(VERSION)),
        )

    def test_a_role_without_a_recorded_version_still_fails_the_pin_policy(
        self,
    ) -> None:
        with self.assertRaises(AssertionError):
            self._pin_policy(self._repo(""))


if __name__ == "__main__":
    unittest.main()
