"""The gpu gate of web-svc-libretranslate.

`resource_filter` reads the flag where `lookup('config', ...)` returned false
for the same declaration, which silently shipped a CPU image twice. The image
tag and the assert task both hang off this one expression.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from plugins.filter.resource_filter import resource_filter
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = "web-svc-libretranslate"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
SERVICES = ROLE_DIR / ROLE_FILE_META_SERVICES


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestGpuGate(unittest.TestCase):
    services: ClassVar[dict] = load_yaml(str(SERVICES))

    def _render(self, expression: str, applications: dict) -> str:
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
        env.filters["resource_filter"] = resource_filter
        env.filters["bool"] = _ansible_bool
        env.globals["lookup"] = lambda name, *a, **k: applications
        return env.from_string(expression).render(application_id=ROLE)

    def test_the_role_declares_the_gpu_flag(self) -> None:
        self.assertTrue(self.services["libretranslate"].get("gpu"))

    def test_the_declared_flag_reaches_the_gate(self) -> None:
        expression = load_yaml(str(VARS))["LIBRETRANSLATE_GPU"]
        rendered = self._render(expression, {ROLE: {"services": self.services}})

        self.assertTrue(_ansible_bool(rendered))

    def test_a_service_without_the_flag_keeps_the_gate_closed(self) -> None:
        expression = load_yaml(str(VARS))["LIBRETRANSLATE_GPU"]
        plain = {
            "libretranslate": {
                k: v for k, v in self.services["libretranslate"].items() if k != "gpu"
            }
        }
        rendered = self._render(expression, {ROLE: {"services": plain}})

        self.assertFalse(_ansible_bool(rendered))


if __name__ == "__main__":
    unittest.main()
