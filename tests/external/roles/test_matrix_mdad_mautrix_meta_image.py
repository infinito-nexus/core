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
_ROLE_VAR = "MATRIX_ADDON_MAUTRIX_META_VERSION"
_BRIDGES = ("messenger", "instagram")
_TAG_PREFIX = {"messenger": "", "instagram": "ig-"}


def _version() -> str:
    return load_yaml_any(str(_ADDON))["version"]


def _upstream_var(bridge: str, suffix: str) -> str:
    return f"matrix_bridge_mautrix_meta_{bridge}_{suffix}"


def _upstream_defaults(bridge: str) -> str:
    return f"roles/custom/matrix-bridge-mautrix-meta-{bridge}/{ROLE_FILE_DEFAULTS_MAIN}"


class TestMatrixMdadMautrixMetaImage(unittest.TestCase):
    def test_the_inventory_hands_mdad_the_addon_version(self) -> None:
        self.assertIn(
            f"{_ROLE_VAR}: \"{{{{ lookup('config', application_id, "
            "'addons.mautrix-meta.version') }}\"",
            read_text(str(_VARS_MAIN)),
        )
        lines = read_text(str(_MDAD_VARS)).splitlines()
        for bridge in _BRIDGES:
            with self.subTest(bridge=bridge):
                self.assertIn(
                    f'{_upstream_var(bridge, "version")}: "{{{{ {_ROLE_VAR} }}}}"',
                    lines,
                )

    def test_the_pin_derives_each_tag_from_the_version(self) -> None:
        for bridge in _BRIDGES:
            with self.subTest(bridge=bridge):
                version = re.escape(_upstream_var(bridge, "version"))
                tag_line = (
                    rf"^{_upstream_var(bridge, 'container_image_tag')}: "
                    rf'"{_TAG_PREFIX[bridge]}\{{\{{ {version} \}}\}}'
                )
                self.assertIsNotNone(
                    re.search(
                        tag_line,
                        fetch_mdad_file(self, _upstream_defaults(bridge)),
                        re.MULTILINE,
                    ),
                    f"the MDAD pin no longer pulls {_TAG_PREFIX[bridge]}<version> "
                    f"for {bridge}; this check probes the wrong tag",
                )

    def test_the_addon_version_is_not_older_than_the_pinned_instagram_version(
        self,
    ) -> None:
        name = _upstream_var("instagram", "version")
        pinned = re.search(
            rf"^{name}:\s*(\S+)",
            fetch_mdad_file(self, _upstream_defaults("instagram")),
            re.MULTILINE,
        )
        self.assertIsNotNone(pinned, f"the MDAD pin no longer declares {name}")
        self.assertGreaterEqual(
            version_key(_version()),
            version_key(pinned.group(1)),
            f"the MDAD pin ships {pinned.group(1)}; the mautrix-meta addon "
            "version would hold the bridges back",
        )

    def test_every_bridge_tag_is_published(self) -> None:
        for bridge in _BRIDGES:
            tag = f"{_TAG_PREFIX[bridge]}{_version()}"
            with self.subTest(bridge=bridge, tag=tag):
                published = manifest_exists(_IMAGE, tag)
                if published is None:
                    warning(
                        f"{_IMAGE}:{tag} was not checked (registry unreachable)",
                        title="mautrix-meta tag unverified",
                        file=str(_ADDON.relative_to(PROJECT_ROOT)),
                    )
                    self.skipTest(f"{_IMAGE} unreachable")
                self.assertTrue(
                    published,
                    f"{_IMAGE}:{tag} is not published; dock.mau.dev purged it, "
                    "so move the mautrix-meta addon version to a current release",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
