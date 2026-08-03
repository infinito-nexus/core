"""Strict guard: every ``lookup('container_healthcheck', key)`` call MUST
target a service whose ``meta/services.yml`` entry declares a probe - i.e.
``services.<key>.healthcheck`` exists and carries either a known ``flavor``
or an explicit ``test`` argv.

Why
===

``container_healthcheck`` (``plugins/lookup/container_healthcheck.py``) is
the SPOT for container probes: the call site passes only the service name,
everything else comes from the service's services config. A service that
declares no probe makes the lookup raise while the compose file is being
rendered:

    container_healthcheck: '<app>' service '<key>' declares no
    healthcheck.flavor, so healthcheck.test is required.

That only surfaces during a deploy, one role at a time. This lint replays
the lookup's own validation against the static config so the failure is
caught before CI ever deploys, and additionally rejects probe declarations
the lookup would refuse at render time (unknown flavor, or a ``flavor``
and a ``test`` fighting over the same entry).

Resolution scope: literal service keys, the ``service_name`` Jinja variable
resolved against the nearest preceding ``{% set service_name = ... %}``,
``entity_name``, ``application_id | get_entity_name``, and role var
constants (``CHESS_SERVICE``) whose ``vars/main.yml`` value resolves the
same way. Any other dynamic expression (loop variables) is skipped - it
cannot be resolved statically.

Per-line opt-out: ``# nocheck: container-healthcheck-probe`` on the
offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_application_defaults
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml
from utils.docker.healthcheck import PROBES, known_flavors
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_RULE = "container-healthcheck-probe"

_SCAN_PREFIX = "roles/"
_SCAN_EXTENSIONS = (".j2",)

_CALL = re.compile(
    r"""lookup\(\s*['"]container_healthcheck['"]\s*,\s*([^,)]+?)\s*[,)]"""
)
_SET_SERVICE_NAME = re.compile(r"""\{%-?\s*set\s+service_name\s*=\s*(.+?)\s*-?%\}""")
_LITERAL = re.compile(r"""^['"]([^'"]+)['"]$""")
_INTERPOLATION = re.compile(r"""^\{\{\s*(.+?)\s*\}\}$""")
_ROLE_VAR = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENTITY_NAME_EXPRESSIONS = ("entity_name", "application_id | get_entity_name")


def _role_app_id(rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "roles":
        return parts[1]
    return None


def _resolve_expression(expression: str, app: str) -> str | None:
    """Resolve a service-key expression to a literal key.

    Args:
        expression: the Jinja expression the call site passed.
        app: the application id owning the template.
    """
    literal = _LITERAL.match(expression.strip())
    if literal:
        return _resolve_expression(literal.group(1), app) or literal.group(1)
    normalized = " ".join(expression.split())
    interpolation = _INTERPOLATION.match(normalized)
    if interpolation:
        return _resolve_expression(interpolation.group(1), app)
    if normalized in _ENTITY_NAME_EXPRESSIONS:
        return get_entity_name(app)
    if _ROLE_VAR.match(normalized):
        return _resolve_role_var(normalized, app)
    return None


def _resolve_role_var(name: str, app: str) -> str | None:
    """Resolve a role var constant against the role's ``vars/main.yml``.

    Args:
        name: the upper-case var name the template referenced.
        app: the application id owning the template.
    """
    role_vars = load_yaml(
        PROJECT_ROOT / "roles" / app / ROLE_FILE_VARS_MAIN, default_if_missing={}
    )
    value = role_vars.get(name)
    return _resolve_expression(value, app) if isinstance(value, str) else None


def _resolve_service_key(
    argument: str, lines: list[str], index: int, app: str
) -> str | None:
    """Resolve the service key a ``container_healthcheck`` call targets.

    Args:
        argument: the call's first argument as written.
        lines: the template's lines.
        index: zero-based line index of the call.
        app: the application id owning the template.
    """
    if argument.strip() != "service_name":
        return _resolve_expression(argument, app)
    for line in reversed(lines[: index + 1]):
        assignment = _SET_SERVICE_NAME.search(line)
        if assignment:
            return _resolve_expression(assignment.group(1), app)
    return None


def _probe_defect(services: dict[str, Any], key: str) -> str | None:
    """Report why a service's probe declaration would fail at render time.

    Args:
        services: the application's ``services`` mapping.
        key: the service key the call site targets.
    """
    if key not in services:
        return f"service '{key}' missing in services config"
    config = services[key].get("healthcheck")
    if not isinstance(config, dict):
        return (
            f"service '{key}' declares no healthcheck.flavor, so healthcheck.test "
            f"is required. Known flavors: {known_flavors()}"
        )
    flavor = str(config.get("flavor", "") or "").strip()
    if not flavor and not config.get("test"):
        return (
            f"service '{key}' healthcheck has neither flavor nor test. "
            f"Known flavors: {known_flavors()}"
        )
    if flavor and flavor not in PROBES:
        return f"service '{key}' has unknown flavor '{flavor}'"
    if flavor and config.get("test"):
        return (
            f"service '{key}' declares both flavor '{flavor}' and test; "
            "the test would be ignored"
        )
    return None


class TestContainerHealthcheckRequiresProbe(unittest.TestCase):
    def test_healthcheck_call_sites_target_declared_probes(self) -> None:
        apps = get_application_defaults()
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_SCAN_EXTENSIONS,
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_SCAN_PREFIX):
                continue
            app = _role_app_id(rel)
            if app not in apps:
                continue
            lines = content.splitlines()
            for index, line in enumerate(lines):
                for match in _CALL.finditer(line):
                    key = _resolve_service_key(match.group(1), lines, index, app)
                    if key is None:
                        continue
                    defect = _probe_defect(apps[app].get("services", {}) or {}, key)
                    if defect and not is_suppressed_at(
                        lines, index + 1, _RULE, mode="same-or-above"
                    ):
                        findings.append((rel, index + 1, f"'{app}' {defect}"))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {msg}"
                for p, n, msg in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "container_healthcheck() calls target services without a usable "
                "probe. Declare `healthcheck.flavor` (or an explicit "
                "`healthcheck.test`) on the service in the role's "
                "`meta/services.yml`, or mark a deliberate exception with "
                f"`# nocheck: {_RULE}`.\n\nOffenders:\n{formatted}"
            )

    def test_declared_probes_are_renderable(self) -> None:
        findings: list[str] = []
        for app, config in sorted(get_application_defaults().items()):
            services = config.get("services", {}) or {}
            for key in sorted(services):
                if not isinstance(services[key].get("healthcheck"), dict):
                    continue
                defect = _probe_defect(services, key)
                if defect:
                    findings.append(f"- {app}: {defect}")

        if findings:
            self.fail(
                "services declare healthcheck blocks the container_healthcheck "
                "lookup would refuse at render time:\n\n" + "\n".join(findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
