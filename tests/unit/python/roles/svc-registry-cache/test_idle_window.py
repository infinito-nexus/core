from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-registry-cache"
SIZE_KEYS = {"max_size", "blobstore_max", "max_size_gb"}


def _services() -> dict:
    return load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))


def _environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["int"] = int
    return env


def rendered_ttl(services: dict) -> str:
    """
    Args:
        services: the role's meta/services.yml the config lookup answers from.

    Returns:
        The REGISTRY_PROXY_TTL line of the registry's env file, rendered.
    """

    def lookup(name, application_id, path):
        if (name, application_id) != ("config", ROLE.name):
            raise AssertionError(f"unexpected lookup {name!r} {application_id!r}")
        node = {"services": services}
        for part in path.split("."):
            node = node[part]
        return node

    env = _environment()
    ttl = env.from_string(
        load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))["REGISTRY_CACHE_PROXY_TTL"]
    ).render(lookup=lookup, application_id=ROLE.name)
    (line,) = [
        line
        for line in read_text(str(ROLE / "templates" / "env.j2")).splitlines()
        if line.startswith("REGISTRY_PROXY_TTL=")
    ]
    return env.from_string(line).render(REGISTRY_CACHE_PROXY_TTL=ttl)


class TestRegistryCacheIdleWindow(unittest.TestCase):
    def test_the_role_defaults_to_the_30_day_window(self) -> None:
        self.assertEqual(_services()["cache"]["max_idle_days"], 30)

    def test_the_registry_flavor_keeps_no_size_cap(self) -> None:
        cache = _services()["cache"]
        self.assertEqual(SIZE_KEYS & set(cache), set())
        self.assertNotIn(
            "REGISTRY_STORAGE_MAXSIZE", read_text(str(ROLE / "templates" / "env.j2"))
        )

    def test_the_window_reaches_the_registry_as_its_proxy_ttl_in_hours(self) -> None:
        self.assertEqual(rendered_ttl(_services()), "REGISTRY_PROXY_TTL=720h")
        self.assertEqual(
            rendered_ttl({"cache": {"max_idle_days": 2}}), "REGISTRY_PROXY_TTL=48h"
        )


if __name__ == "__main__":
    unittest.main()
