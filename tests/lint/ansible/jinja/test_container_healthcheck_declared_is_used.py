"""Strict guard: a declared ``healthcheck`` MUST reach a compose file.

``services.<key>.healthcheck`` only becomes a probe when a template renders it
through ``{{ lookup('container_healthcheck', <key>) }}``. Without that call the
block is dead configuration: it reads like the service is watched, the compose
file carries nothing, and the container counts as healthy the moment its
process starts.

[test_container_healthcheck_requires_probe.py](test_container_healthcheck_requires_probe.py)
guards the opposite direction - every call site must find a usable declaration.
Together the two make the pair total.

Resolution of the call's service key is the sibling's, imported rather than
restated, so both directions always agree on what a call site names.

Per-entry opt-out: ``# nocheck: container-healthcheck-unused`` on the service
key, on its ``healthcheck:`` line, or on the line immediately above either.
Reserved for a declaration a template emits some other way - a literal block
built from the same values, or a partial owned by another role.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_application_defaults
from utils.cache.files import iter_project_files_with_content, read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT
from .test_container_healthcheck_requires_probe import (
    _CALL,
    _resolve_service_key,
    _role_app_id,
)

RULE = "container-healthcheck-unused"
SCAN_PREFIX = "roles/"
SCAN_EXTENSIONS = (".j2",)


def called_service_keys() -> dict[str, set[str]]:
    """Every service key a ``container_healthcheck`` call resolves to, per role."""
    apps = get_application_defaults()
    called: dict[str, set[str]] = {}
    for path_str, content in iter_project_files_with_content(
        extensions=SCAN_EXTENSIONS,
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith(SCAN_PREFIX):
            continue
        app = _role_app_id(rel)
        if app not in apps:
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            for match in _CALL.finditer(line):
                key = _resolve_service_key(match.group(1), lines, index, app)
                if key is not None:
                    called.setdefault(app, set()).add(key)
    return called


def suppressed(app: str, key: str) -> bool:
    """Whether the service entry or its healthcheck line carries the marker."""
    path = PROJECT_ROOT / "roles" / app / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return False
    lines = read_text(path).splitlines()
    inside = False
    for number, line in enumerate(lines, start=1):
        if line.startswith(f"{key}:"):
            if is_suppressed_at(lines, number, RULE):
                return True
            inside = True
            continue
        if inside:
            if line and not line[0].isspace():
                return False
            if line.strip().startswith("healthcheck:"):
                return is_suppressed_at(lines, number, RULE)
    return False


class TestContainerHealthcheckDeclaredIsUsed(unittest.TestCase):
    def test_every_declared_probe_reaches_a_template(self) -> None:
        called = called_service_keys()
        findings: list[str] = []
        for app, config in sorted(get_application_defaults().items()):
            services = config.get("services", {}) or {}
            for key in sorted(services):
                entry = services[key]
                if not isinstance(entry, dict):
                    continue
                if not isinstance(entry.get("healthcheck"), dict):
                    continue
                if key in called.get(app, set()):
                    continue
                if suppressed(app, key):
                    continue
                findings.append(f"- {app}: '{key}' declares a healthcheck")

        if findings:
            self.fail(
                "these services declare a healthcheck no template renders, so "
                "the compose file carries no probe and the container passes as "
                "healthy the moment it starts. Add "
                "`{{ lookup('container_healthcheck', service_name) | indent(4) }}` "
                "to the service block, or mark the entry "
                f"`# nocheck: {RULE}`.\n\n" + "\n".join(findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
