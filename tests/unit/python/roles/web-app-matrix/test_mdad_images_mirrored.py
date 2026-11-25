from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.docker.image.discovery import iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_ROLE = "web-app-matrix"
_ROLE_DIR = PROJECT_ROOT / "roles" / _ROLE
_MDAD_VARS = _ROLE_DIR / "templates/flavor/ansible/vars.yml.j2"
_SERVICES = _ROLE_DIR / ROLE_FILE_META_SERVICES
_DOCKER_HUB_COMPONENT_IMAGES = (
    "matrix_bridge_heisenbridge_container_image",
    "matrix_static_files_container_image",
    "livekit_server_container_image",
)
_IMAGE_LOOKUP = re.compile(
    r"^(?P<var>\w+_container_image): \"\{\{ lookup\('image', application_id, "
    r"'(?P<key>[\w-]+)', tag_only=True\) \}\}\"$",
    re.MULTILINE,
)


def _routed_images() -> dict[str, str]:
    """
    Returns:
        ``{<MDAD image variable>: <meta/services.yml key>}``.
    """
    return {
        match["var"]: match["key"]
        for match in _IMAGE_LOOKUP.finditer(read_text(str(_MDAD_VARS)))
    }


class TestMdadImagesMirrored(unittest.TestCase):
    def test_every_docker_hub_component_image_comes_from_the_image_lookup(
        self,
    ) -> None:
        routed = _routed_images()
        for var in _DOCKER_HUB_COMPONENT_IMAGES:
            with self.subTest(var=var):
                self.assertIn(
                    var,
                    routed,
                    f"vars.yml.j2 leaves {var} at MDAD's docker.io default, so "
                    "CI pulls it from Docker Hub anonymously",
                )

    def test_every_routed_image_is_a_mirror_only_entry(self) -> None:
        services = load_yaml(_SERVICES)
        for var, key in _routed_images().items():
            with self.subTest(var=var, key=key):
                entry = services.get(key)
                self.assertIsInstance(
                    entry,
                    dict,
                    f"{var} reads services.{key}, which meta/services.yml "
                    "does not declare",
                )
                self.assertIs(
                    entry.get("enabled"),
                    False,
                    f"services.{key} must stay mirror-only (enabled: false); "
                    "MDAD runs the container, not this role",
                )
                self.assertTrue(entry.get("image"), f"services.{key} has no image")
                self.assertTrue(entry.get("version"), f"services.{key} has no version")

    def test_the_mirror_sync_discovers_every_routed_image(self) -> None:
        discovered = {
            ref.service: ref
            for ref in iter_role_images(PROJECT_ROOT)
            if ref.role == _ROLE and not ref.derived
        }
        for var, key in _routed_images().items():
            with self.subTest(var=var, key=key):
                self.assertIn(
                    key,
                    discovered,
                    f"the mirror sync never sees services.{key}, so CI has no "
                    f"GHCR copy for {var} to pull",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
