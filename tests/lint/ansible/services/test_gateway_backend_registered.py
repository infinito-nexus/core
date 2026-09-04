"""Lint: every model backend the gateway declares is also routed by it.

``svc-ai-litellm`` names each backend twice: once as a ``meta/services.yml``
flag that pulls the backend role into the deployment, and once as a
``model_list`` branch in ``templates/config.yaml.j2`` that gives it a model
alias. Only the second one routes. A backend declared without its branch
deploys, consumes its memory and storage budget, and answers nothing, because
no alias resolves to it.

The scan reads the flags rather than a list, so adding a backend flag without
wiring the alias fails here instead of at the first prompt.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: gateway-backend-registered`` on the flag's ``enabled`` line or
  the non-empty line above it.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "gateway-backend-registered"
_GATEWAY_ROLE = "svc-ai-litellm"
_GATEWAY_CONFIG = "templates/config.yaml.j2"

_BACKEND_FLAG = re.compile(r"'(?P<role>svc-ai-[a-z0-9-]+)'\s+in\s+group_names")


def _gateway_dir():
    return PROJECT_ROOT / "roles" / _GATEWAY_ROLE


def _declared_backends() -> dict[str, str]:
    """Return ``{backend role id: flag name}`` for every backend flag."""
    services_path = _gateway_dir() / ROLE_FILE_META_SERVICES
    services = load_yaml_any(str(services_path), default_if_missing={})
    lines = read_text(str(services_path)).splitlines()
    backends: dict[str, str] = {}
    if not isinstance(services, Mapping):
        return backends
    for flag, block in services.items():
        if not isinstance(block, Mapping):
            continue
        match = _BACKEND_FLAG.search(str(block.get("enabled") or ""))
        if not match:
            continue
        line_no = next(
            (i + 1 for i, line in enumerate(lines) if line.startswith(f"{flag}:")),
            1,
        )
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        backends[match["role"]] = flag
    return backends


class TestGatewayBackendRegistered(unittest.TestCase):
    def test_every_declared_backend_has_a_model_list_branch(self) -> None:
        config = read_text(str(_gateway_dir() / _GATEWAY_CONFIG))
        missing = [
            f"{role} (flag '{flag}'): pulled into the deployment but "
            f"{_GATEWAY_ROLE}/{_GATEWAY_CONFIG} never branches on it, so no "
            f"model alias routes to it"
            for role, flag in sorted(_declared_backends().items())
            if role not in config
        ]
        self.assertEqual(
            [],
            missing,
            f"gateway backend(s) without a model_list branch ({len(missing)}):\n"
            + "\n".join(f"  - {m}" for m in missing),
        )

    def test_the_scan_finds_backend_flags(self) -> None:
        self.assertTrue(
            _declared_backends(),
            f"{_GATEWAY_ROLE} declares no svc-ai-* backend flag, so the rule "
            "would pass vacuously; check that the scan still reads the right "
            "topic",
        )


if __name__ == "__main__":
    unittest.main()
