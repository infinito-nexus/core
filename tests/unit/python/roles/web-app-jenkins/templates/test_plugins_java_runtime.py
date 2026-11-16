from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_SERVICES
from utils.update.base import is_semver, version_key

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-jenkins"
PLUGINS = "roles/web-app-jenkins/templates/plugins.txt.j2"
IMAGE_DEFAULT_JAVA = 21
JAVA_FLOORS = {"mattermost": ("3.2.0", 25)}


def controller_java() -> int:
    services = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
    match = re.search(r"-jdk(\d+)", str(services["jenkins"]["version"]))
    return int(match.group(1)) if match else IMAGE_DEFAULT_JAVA


def rendered_plugins() -> dict[str, str]:
    addons = [
        {"key": path.stem, "value": load_yaml_any(str(path))}
        for path in sorted((ROLE / ROLE_DIR_META_ADDONS).glob("*.yml"))
    ]
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    text = env.get_template(PLUGINS).render(JENKINS_PLUGIN_ADDONS=addons)
    return dict(line.split(":", 1) for line in text.splitlines() if line.strip())


def java_violations(plugins: dict[str, str], java: int) -> list[str]:
    found: list[str] = []
    for plugin, (floor, required) in JAVA_FLOORS.items():
        if plugin not in plugins or java >= required:
            continue
        version = plugins[plugin]
        if not is_semver(version) or version_key(version) >= version_key(floor):
            found.append(
                f"{plugin}:{version} resolves to a release built for Java "
                f"{required} (from {floor} on), the controller runs Java {java}"
            )
    return found


class TestPluginsRunOnControllerJava(unittest.TestCase):
    def test_rendered_plugin_list_fits_the_controller_java(self) -> None:
        self.assertEqual(java_violations(rendered_plugins(), controller_java()), [])

    def test_a_moving_or_newer_release_is_refused_on_an_older_java(self) -> None:
        for version in ("latest", "3.2.0"):
            with self.subTest(version=version):
                self.assertTrue(java_violations({"mattermost": version}, 21))

    def test_a_controller_on_the_required_java_takes_the_newer_release(self) -> None:
        self.assertEqual(java_violations({"mattermost": "3.2.0"}, 25), [])


if __name__ == "__main__":
    unittest.main()
