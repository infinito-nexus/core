from __future__ import annotations

import base64
import json
import unittest

from ansible.plugins.filter.core import combine
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-matomo"
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
PLUGINS = ("templates/design_plugin.j2", "templates/rbac_login_plugin.j2")


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["from_json"] = json.loads
    env.filters["to_json"] = json.dumps
    env.filters["combine"] = combine
    env.filters["b64encode"] = lambda text: base64.b64encode(text.encode()).decode()
    env.globals["lookup"] = lambda _kind, path: read_text(str(ROLE / "files" / path))
    return env


def _require(version: str) -> str:
    """
    Args:
        version: the Matomo release the role deploys.

    Returns:
        the range MATOMO_PLUGIN_REQUIRE renders for it.
    """
    return (
        _environment()
        .from_string(VARS["MATOMO_PLUGIN_REQUIRE"])
        .render(MATOMO_VERSION=version)
    )


def _manifest(template: str, version: str) -> dict:
    """
    Args:
        template: the plugin template, relative to the role.
        version: the Matomo release the role deploys.

    Returns:
        the plugin.json the template ships into the plugin directory.
    """
    rendered = (
        _environment()
        .from_string(read_text(str(ROLE / template)))
        .render(
            MATOMO_PLUGIN_REQUIRE=_require(version),
            matomo_design_assets={"results": []},
        )
    )
    line = next(
        entry for entry in rendered.splitlines() if entry.startswith("plugin.json ")
    )
    return json.loads(base64.b64decode(line.split(" ", 1)[1]))


class TestPluginsRequireTheDeployedMajor(unittest.TestCase):
    def test_the_range_spans_the_deployed_major_only(self) -> None:
        self.assertEqual(_require("6.0.0"), ">=6.0.0-b1,<7.0.0-b1")
        self.assertEqual(_require("5.12.3"), ">=5.0.0-b1,<6.0.0-b1")

    def test_every_own_plugin_requires_the_major_of_the_deployed_release(
        self,
    ) -> None:
        for template in PLUGINS:
            for version in ("5.12.3", "6.0.0"):
                with self.subTest(template=template, version=version):
                    self.assertEqual(
                        _manifest(template, version)["require"],
                        {"matomo": _require(version)},
                    )


if __name__ == "__main__":
    unittest.main()
