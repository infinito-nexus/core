"""The mautrix-meta Instagram image the ansible flavor pulls is still published.

dock.mau.dev keeps the plain ``v*`` tags of mautrix/meta but purges old ``ig-``
tags, so the ``ig-v0.2609.0`` the MDAD pin derives is gone and every deploy with
the mautrix-meta addon died pulling it (CI run 44198828712). The addon pins the
Instagram version itself; this check asks the registry for the tag that pin
yields, and fails once a pin bump turns the override into a downgrade. An
unreachable host or registry is reported as unverified, as in the sibling MDAD
check.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.message import warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.docker.registry import manifest_exists
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN
from utils.update.base import version_key

from . import PROJECT_ROOT, fetch_mdad_file

_ROLE = PROJECT_ROOT / "roles/web-app-matrix"
_ADDON = _ROLE / "meta/addons/mautrix-meta.yml"
_VARS_MAIN = _ROLE / ROLE_FILE_VARS_MAIN
_MDAD_VARS = _ROLE / "templates/flavor/ansible/vars.yml.j2"
_IMAGE = "dock.mau.dev/mautrix/meta"
_VAR = "matrix_bridge_mautrix_meta_instagram_version"
_TAG_VAR = "matrix_bridge_mautrix_meta_instagram_container_image_tag"
_ROLE_VAR = "MATRIX_ADDON_MAUTRIX_META_INSTAGRAM_VERSION"
_UPSTREAM_DEFAULTS = (
    f"roles/custom/matrix-bridge-mautrix-meta-instagram/{ROLE_FILE_DEFAULTS_MAIN}"
)


def _override() -> str:
    return load_yaml_any(str(_ADDON))["config"]["instagram_version"]


class TestMatrixMdadInstagramImage(unittest.TestCase):
    def test_the_inventory_hands_mdad_the_addon_version(self) -> None:
        self.assertIn(
            f"{_ROLE_VAR}: \"{{{{ lookup('config', application_id, "
            "'addons.mautrix-meta.config.instagram_version') }}\"",
            read_text(str(_VARS_MAIN)),
        )
        self.assertIn(
            f'{_VAR}: "{{{{ {_ROLE_VAR} }}}}"',
            read_text(str(_MDAD_VARS)).splitlines(),
        )

    def test_the_pin_derives_the_tag_from_the_version_with_the_ig_prefix(
        self,
    ) -> None:
        tag_line = rf'^{_TAG_VAR}: "ig-\{{\{{ {_VAR} \}}\}}'
        self.assertIsNotNone(
            re.search(
                tag_line, fetch_mdad_file(self, _UPSTREAM_DEFAULTS), re.MULTILINE
            ),
            "the MDAD pin no longer pulls ig-<version>; this check probes the "
            "wrong tag",
        )

    def test_the_override_is_newer_than_the_pinned_version(self) -> None:
        pinned = re.search(
            rf"^{_VAR}:\s*(\S+)",
            fetch_mdad_file(self, _UPSTREAM_DEFAULTS),
            re.MULTILINE,
        )
        self.assertIsNotNone(pinned, f"the MDAD pin no longer declares {_VAR}")
        self.assertGreater(
            version_key(_override()),
            version_key(pinned.group(1)),
            f"the MDAD pin ships {pinned.group(1)}; drop "
            "config.instagram_version from the mautrix-meta addon, which would "
            "now hold the bridge back",
        )

    def test_the_override_tag_is_published(self) -> None:
        tag = f"ig-{_override()}"
        published = manifest_exists(_IMAGE, tag)
        if published is None:
            warning(
                f"{_IMAGE}:{tag} was not checked (registry unreachable)",
                title="mautrix-meta Instagram tag unverified",
                file=str(_ADDON.relative_to(PROJECT_ROOT)),
            )
            self.skipTest(f"{_IMAGE} unreachable")
        self.assertTrue(
            published,
            f"{_IMAGE}:{tag} is not published; dock.mau.dev purged it, so move "
            "config.instagram_version of the mautrix-meta addon to a current release",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
