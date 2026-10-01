"""Lint: an invokable role pulls a shared service in through its services.yml.

Rationale
=========
``roles/sys-service-loader`` plans a deploy from services edges alone: a
consumer names the provider's service key in its own ``meta/services.yml``,
``plugins/lookup/service.py`` marks that key required, and the loader runs the
provider once, in dependency order, before the application pass.

A role that instead reaches for the provider with ``include_role`` at task
time is invisible to that planner. The provider is never scheduled into the
round, so whatever it establishes is missing for every other consumer, and the
ordering depends on where in the task list the include happens to sit rather
than on the service graph. ``svc-ai-s1`` registered the compose handlers that
way and its ``compose config`` ran before ``/usr/bin/compose`` existed; the
desktop roles chowned into ``/home/<user>`` before the account was created.

Scope
=====
Invokable roles only, and only includes that load a whole role the registry
knows as a service provider (``shared: true`` or ``provides:`` on its primary
entity). An include carrying ``tasks_from`` calls one task file rather than
loading the service, so it is not an edge and stays untouched; so do a
provider reaching into its own internals and an include of a role that
provides nothing.

The rule asks for the declaration, not for the include to go. Once the edge
exists the loader has already run the provider and the include is a no-op
through the provider's own run-once guard.

Per-line opt-out
================
Add ``# nocheck: services-declared-load`` on the ``name:`` line of the include
or the line above it, naming why the edge cannot be a service edge.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.applications.services.registry import (
    build_role_to_primary_service_key,
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.required_by_coverage import role_is_invokable

from . import PROJECT_ROOT

_RULE = "services-declared-load"
ROLES_DIR = PROJECT_ROOT / "roles"


def _owning_role(rel_path: str) -> str:
    parts = Path(rel_path).parts
    return parts[1] if len(parts) > 2 and parts[0] == "roles" else ""


def _relative(path_str: str) -> str:
    path = Path(path_str)
    if path.is_absolute():
        return path.relative_to(PROJECT_ROOT).as_posix()
    return path.as_posix()


def _role_include(task: Mapping) -> Mapping:
    for key in ("include_role", "import_role"):
        include = task.get(key) or task.get(f"ansible.builtin.{key}")
        if isinstance(include, Mapping):
            return include
    return {}


def _walk(tasks: object):
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        yield task
        for section in ("block", "rescue", "always"):
            yield from _walk(task.get(section))


def _declared_keys(role: str) -> set[str]:
    services = load_yaml_any(
        str(ROLES_DIR / role / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    return set(services) if isinstance(services, dict) else set()


def _include_line(lines: list[str], target: str) -> int:
    pattern = re.compile(rf"^\s*name\s*:\s*['\"]?{re.escape(target)}['\"]?\s*(?:#.*)?$")
    for number, line in enumerate(lines, start=1):
        if pattern.match(line):
            return number
    return 0


class TestServicesDeclaredLoad(unittest.TestCase):
    def test_an_invokable_role_declares_the_provider_it_loads(self) -> None:
        registry = build_service_registry_from_roles_dir(ROLES_DIR)
        provider_key = build_role_to_primary_service_key(registry)
        findings: list[str] = []

        for absolute, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
        ):
            path_str = _relative(absolute)
            role = _owning_role(path_str)
            if not role or not role_is_invokable(role, ROLES_DIR):
                continue
            try:
                tasks = load_yaml_str(content)
            except Exception:
                continue
            lines = content.splitlines()
            declared = _declared_keys(role)
            for task in _walk(tasks):
                include = _role_include(task)
                if include.get("tasks_from"):
                    continue
                target = str(include.get("name") or "").strip()
                key = provider_key.get(target, "")
                if not key or target == role or key in declared:
                    continue
                line_no = _include_line(lines, target)
                if line_no and is_suppressed_at(
                    lines, line_no, _RULE, mode="same-or-above"
                ):
                    continue
                findings.append(
                    f"{path_str}:{line_no or 1}: {role} loads {target} with "
                    f"include_role while its {ROLE_FILE_META_SERVICES} names no "
                    f"`{key}:` edge, so the planner never schedules the two together"
                )

        if findings:
            body = "\n".join(f"  - {f}" for f in sorted(set(findings)))
            self.fail(
                f"\n{len(set(findings))} include(s) of a shared service that the "
                f"service graph cannot see:\n{body}\n\n"
                "Fix options:\n"
                "  (a) Add the provider's service key to the role's "
                f"{ROLE_FILE_META_SERVICES} with `enabled: true` and "
                "`shared: true`.\n"
                f"  (b) Add `# nocheck: {_RULE}` on the include's `name:` line, "
                "naming why the edge cannot be a service edge."
            )


if __name__ == "__main__":
    unittest.main()
