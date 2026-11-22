from __future__ import annotations

import itertools
import unittest
from typing import TYPE_CHECKING, Any

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.mounts import mount_when_passes
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

if TYPE_CHECKING:
    from collections.abc import Callable

VOLUMES = PROJECT_ROOT / "roles" / "web-app-taiga" / ROLE_FILE_META_VOLUMES
TARGET = "/usr/share/nginx/html/conf.json"
SERVICES = ("sso", "ldap", "design")


def front_conf_mount() -> dict[str, Any]:
    """
    Returns:
        The one mount that puts a file at the front's ``conf.json``.
    """
    (mount,) = (
        mount
        for entry in load_yaml_any(str(VOLUMES)).values()
        for mount in entry.get("mounts") or []
        if mount.get("service") == "front" and mount.get("target") == TARGET
    )
    return mount


def renderer(enabled: dict[str, bool]) -> Callable[[str], str]:
    """Render a mount's ``when`` the way ``container_volumes`` does.

    Args:
        enabled: ``services.<name>.enabled`` per name of ``SERVICES``.

    Returns:
        A renderer whose ``config`` lookup answers from *enabled*.
    """
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = lambda value: boolean(value, strict=False)

    def lookup(_kind: str, _application_id: str, key: str, *_default: Any) -> bool:
        return enabled[key.split(".")[1]]

    return lambda expression: environment.from_string(expression).render(lookup=lookup)


class TestTheFrontServesTheRoleConf(unittest.TestCase):
    def test_every_service_combination_mounts_the_rendered_conf(self) -> None:
        mount = front_conf_mount()
        for values in itertools.product((False, True), repeat=len(SERVICES)):
            enabled = dict(zip(SERVICES, values, strict=True))
            with self.subTest(**enabled):
                self.assertTrue(mount_when_passes(mount, renderer(enabled)))


if __name__ == "__main__":
    unittest.main()
