from __future__ import annotations

import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-app-discourse"
VARS = ROLE / ROLE_FILE_VARS_MAIN
TEMPLATE = ROLE / "templates" / "config.yml.j2"
_ENV_LINE = re.compile(r"^  UNICORN_WORKERS:.*$", re.MULTILINE)


def _workers(cpus: int, mem_mb: int) -> int:
    """Render ``env.UNICORN_WORKERS`` of the launcher config for one host.

    Args:
        cpus: the host's vCPUs, as ``RESOURCE_HOST_CPUS`` carries them
        mem_mb: the host's RAM in MiB, as ``lookup('resource', 'host_mem_mb')``
            returns it

    Returns:
        the worker count the launcher hands the container
    """

    def lookup(kind: str, key: str) -> int:
        assert (kind, key) == ("resource", "host_mem_mb"), (kind, key)
        return mem_mb

    expression = load_yaml_any(str(VARS))["DISCOURSE_UNICORN_WORKERS"]
    derived = (
        NativeEnvironment(undefined=StrictUndefined)
        .from_string(expression)
        .render(RESOURCE_HOST_CPUS=str(cpus), lookup=lookup)
    )
    line = _ENV_LINE.search(read_text(str(TEMPLATE)))
    assert line is not None, f"{TEMPLATE} sets no UNICORN_WORKERS"
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    rendered = environment.from_string(line[0]).render(
        DISCOURSE_UNICORN_WORKERS=derived
    )
    return int(load_yaml_str(rendered)["UNICORN_WORKERS"])


class TestUnicornWorkers(unittest.TestCase):
    def test_the_count_follows_cpus_and_ram_of_the_host(self) -> None:
        for cpus, mem_mb, expected in (
            (4, 15_983, 3),
            (2, 6_932, 2),
            (2, 65_536, 4),
            (8, 32_768, 8),
            (8, 31_744, 7),
            (16, 65_536, 8),
            (64, 262_144, 8),
            (1, 1_024, 2),
        ):
            with self.subTest(cpus=cpus, mem_mb=mem_mb):
                self.assertEqual(_workers(cpus, mem_mb), expected)


if __name__ == "__main__":
    unittest.main()
