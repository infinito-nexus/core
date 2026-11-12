"""The gpu gate of web-svc-libretranslate.

`lookup('config', ...)` returned false for the same declaration the service
carries, which silently shipped a CPU image twice. The image tag and the
assert task both hang off this one expression, so what it asks and which
service key it names is what this guards. Whether a declared flag and a
present device add up to a yes belongs to the ``gpu`` lookup's own tests.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = "web-svc-libretranslate"
SERVICE = "libretranslate"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
SERVICES = ROLE_DIR / ROLE_FILE_META_SERVICES


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestGpuGate(unittest.TestCase):
    services: ClassVar[dict] = load_yaml(str(SERVICES))

    def _render(self, expression: str, answer) -> tuple[str, list]:
        """Render ``expression`` against a recording ``lookup``.

        Args:
            expression: the var expression to render.
            answer: what the ``gpu`` lookup answers.

        Returns:
            The rendered string and the ``(name, terms)`` of every lookup.
        """
        asked: list = []
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
        env.filters["bool"] = _ansible_bool

        def _lookup(name, *terms, **_kwargs):
            asked.append((name, terms))
            return answer if name == "gpu" else {}

        env.globals["lookup"] = _lookup
        return env.from_string(expression).render(application_id=ROLE), asked

    def test_the_role_declares_the_gpu_flag(self) -> None:
        self.assertTrue(self.services[SERVICE].get("gpu"))

    def test_the_gate_asks_the_gpu_lookup_for_this_service(self) -> None:
        expression = load_yaml(str(VARS))["LIBRETRANSLATE_GPU"]

        _rendered, asked = self._render(expression, True)

        self.assertIn(("gpu", (ROLE, SERVICE)), asked)

    def test_a_yes_from_the_lookup_opens_the_gate(self) -> None:
        expression = load_yaml(str(VARS))["LIBRETRANSLATE_GPU"]

        rendered, _asked = self._render(expression, True)

        self.assertTrue(_ansible_bool(rendered))

    def test_a_no_from_the_lookup_keeps_the_gate_closed(self) -> None:
        expression = load_yaml(str(VARS))["LIBRETRANSLATE_GPU"]

        rendered, _asked = self._render(expression, False)

        self.assertFalse(_ansible_bool(rendered))


if __name__ == "__main__":
    unittest.main()
