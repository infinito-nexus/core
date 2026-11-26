from __future__ import annotations

import re
import unittest

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.annotations.message import warning
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
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


def _jinja() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = boolean
    return env


def _rendered_role_version() -> str:
    """
    Returns:
        The role's version variable, rendered against a config lookup that
        answers the addon's version.
    """

    def lookup(*args):
        if args != ("config", _ROLE.name, "addons.mautrix-meta.version"):
            raise AssertionError(f"{_ROLE_VAR} reads lookup{args!r}")
        return _version()

    return (
        _jinja()
        .from_string(load_yaml_any(str(_VARS_MAIN))[_ROLE_VAR])
        .render(lookup=lookup, application_id=_ROLE.name)
    )


def _rendered_mdad_vars(version: str) -> dict:
    """
    Args:
        version: the value of the role's version variable.

    Returns:
        The MDAD variables the mautrix-meta block of the MDAD vars template
        renders with the bridge enabled.
    """
    lines = read_text(str(_MDAD_VARS)).splitlines()
    start = next(
        i
        for i, row in enumerate(lines)
        if row.startswith("{% if MATRIX_BRIDGE.mautrix_meta")
    )
    end = next(i for i in range(start, len(lines)) if lines[i] == "{% endif %}")
    rendered = (
        _jinja()
        .from_string("\n".join(lines[start : end + 1]))
        .render(
            MATRIX_BRIDGE={"mautrix_meta": True},
            **{_ROLE_VAR: version},
        )
    )
    return load_yaml_str(rendered) or {}


class TestMatrixMdadMautrixMetaImage(unittest.TestCase):
    def test_the_inventory_hands_mdad_the_addon_version(self) -> None:
        version = _rendered_role_version()
        self.assertEqual(version, _version())
        rendered = _rendered_mdad_vars(version)
        for bridge in _BRIDGES:
            with self.subTest(bridge=bridge):
                self.assertEqual(rendered[_upstream_var(bridge, "version")], _version())

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
