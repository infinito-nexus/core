"""Strict guard: every ``lookup('container_address', app, key)`` call MUST
target a service that declares the attribute the lookup needs - i.e. the
resolved ``services.<key>`` entry must exist in the target app's services
config and carry a non-empty ``name:``.

Why
===

``container_address`` (``plugins/lookup/container_address.py``) resolves a
service's address off ``services.<key>.name``. When the key is missing from
the app's services config, or the entry has no ``name``, the lookup raises
at *task-arg finalization* time:

    container_address: service '<key>' missing in '<app>' services config
    container_address: services.<key>.name not set for '<app>'

That only surfaces during a deploy (it killed the compose jobs for
``web-app-erpnext`` - ``container_address(.., 'backend')`` with no
``backend`` service - and ``web-app-friendica`` - the ``friendica`` service
had no ``name``). This lint replays the lookup's own resolution
(`_resolve_bare_name`) against the static config so the failure is caught
before CI ever deploys.

Resolution scope: literal app ids, the ``application_id`` var (the role's
own id), literal service keys, and the ``entity_name`` var are resolved;
any other dynamic arg expression is skipped (cannot be resolved statically).

Per-line opt-out: ``# nocheck: container-address-service-name`` on the
offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.container_address import _resolve_bare_name
from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_application_defaults
from utils.cache.files import iter_project_files_with_content
from utils.roles.entity.name import get_entity_name

from . import PROJECT_ROOT

_RULE = "container-address-service-name"

_SCAN_PREFIXES = ("roles/", "scripts/")
_SCAN_EXTENSIONS = (".yml", ".j2", ".py")

_CALL = re.compile(
    r"""lookup\(\s*['"]container_address['"]\s*,\s*([^,]+?)\s*,\s*([^,)]+?)\s*[,)]"""
)
_LITERAL = re.compile(r"""^['"]([^'"]+)['"]$""")


def _role_app_id(rel_path: str) -> str | None:
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "roles":
        return parts[1]
    return None


def _resolve_app(arg: str, rel_path: str, apps: dict) -> str | None:
    literal = _LITERAL.match(arg.strip())
    if literal:
        return literal.group(1)
    if arg.strip() == "application_id":
        rid = _role_app_id(rel_path)
        return rid if rid in apps else None
    return None


def _resolve_key(arg: str, app: str) -> str | None:
    literal = _LITERAL.match(arg.strip())
    if literal:
        return literal.group(1)
    if arg.strip() == "entity_name":
        return get_entity_name(app)
    if arg.strip() == "application_id":
        return app
    return None


class TestContainerAddressRequiresServiceName(unittest.TestCase):
    def test_container_address_targets_declare_name(self) -> None:
        apps = get_application_defaults()
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_SCAN_EXTENSIONS,
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not any(rel.startswith(prefix) for prefix in _SCAN_PREFIXES):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                for match in _CALL.finditer(line):
                    app = _resolve_app(match.group(1), rel, apps)
                    if app is None:
                        continue
                    key = _resolve_key(match.group(2), app)
                    if key is None:
                        continue
                    try:
                        _resolve_bare_name(apps, app, key)
                    except AnsibleError as exc:
                        if is_suppressed_at(
                            lines, idx + 1, _RULE, mode="same-or-above"
                        ):
                            continue
                        findings.append((rel, idx + 1, str(exc)))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {msg}"
                for p, n, msg in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "container_address() calls target services that do not "
                "declare the required `name`. Each target service must exist "
                "in the app's services config with a non-empty `name:` (the "
                "entity-name fallback applies only for the literal key "
                "'application'). Add the missing service/name, or mark a "
                "deliberate exception with "
                "`# nocheck: container-address-service-name`.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
