"""Integration test: every role that participates in the variant-aware
service registry MUST guard ``tasks/main.yml`` with a
``run_once_<role_slug>`` flag.

A role participates in the registry when **any** of the following
holds:

  (a) Self-declared shared: its primary entity in ``meta/services.yml``
      carries ``shared: true``.
  (b) Self-declared via ``provides:`` or alias entries that point at the
      primary entity (mirrors ``utils.roles.applications.services.registry``).
  (c) Consumer-activated: at least one other role's ``meta/services.yml``
      declares ``services.<provider-key>.enabled: true; shared: true``,
      which the variant-aware deploy planner resolves to this role.

In every case the role can be pulled in dynamically by
``sys-service-loader``'s ``load_app.yml`` (which gates inclusion
on ``run_once_<role>``) — both directly when listed in ``apps=`` and
transitively when a consumer's variant aktivates it. Without the guard
in ``tasks/main.yml`` the loader can include the role multiple times
and trigger duplicate execution or infinite recursion.

The check is deliberately permissive about the EXACT shape of the
guard — direct ``- include_tasks: 01_core.yml`` calls, ``block:``-
wrapped task lists, and any other YAML structure are accepted as long
as the literal ``run_once_<role_slug>`` token appears somewhere in
``tasks/main.yml``. The companion lint at
``tests/lint/ansible/roles/test_service_core_first_task_run_once.py``
enforces the canonical ``include_tasks: 01_core.yml + when: run_once_…``
shape on top of this baseline.
"""

import re
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT


def _role_slug(role_name: str) -> str:
    return role_name.replace("-", "_")


def _consumer_activated_provider_roles(roles_dir: Path, registry: dict) -> set[str]:
    """For every ``services.<X>.enabled: true; shared: true`` claim in
    any role's ``meta/services.yml``, return the resolved provider role
    name (when ``<X>`` is registered)."""
    activated: set[str] = set()
    for role_path in sorted(roles_dir.iterdir()):
        if not role_path.is_dir():
            continue
        services_file = role_path / ROLE_FILE_META_SERVICES
        if not services_file.is_file():
            continue
        data = load_yaml(services_file, default_if_missing={}) or {}
        if not isinstance(data, dict):
            continue
        for service_key, conf in data.items():
            if not isinstance(conf, dict):
                continue
            if conf.get("enabled") is True and conf.get("shared") is True:
                entry = registry.get(service_key)
                if isinstance(entry, dict):
                    role_name = entry.get("role")
                    if isinstance(role_name, str) and role_name:
                        activated.add(role_name)
    return activated


def _self_declared_provider_roles_from_registry(registry: dict) -> set[str]:
    """Return the set of unique provider role names from the registry.
    Skip alias entries (they re-point to a canonical primary)."""
    providers: set[str] = set()
    for entry in registry.values():
        if not isinstance(entry, dict):
            continue
        if "canonical" in entry:
            continue
        role_name = entry.get("role")
        if isinstance(role_name, str) and role_name:
            providers.add(role_name)
    return providers


class TestSharedServiceRunOnceGuard(unittest.TestCase):
    def test_every_shared_service_role_has_run_once_guard(self):
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        registry = build_service_registry_from_roles_dir(roles_dir)

        # Union of (a)/(b) self-declared providers and (c) consumer-
        # activated providers. Any role in this set can be pulled in
        # dynamically and therefore needs the guard.
        provider_roles = _self_declared_provider_roles_from_registry(registry)
        provider_roles |= _consumer_activated_provider_roles(roles_dir, registry)

        violations: list[str] = []
        for role_name in sorted(provider_roles):
            role_path = roles_dir / role_name
            if not role_path.is_dir():
                violations.append(
                    f"{role_name}: registered as a service provider but "
                    f"roles/{role_name}/ does not exist."
                )
                continue

            main_yml = role_path / ROLE_FILE_TASKS_MAIN
            if not main_yml.is_file():
                violations.append(
                    f"{role_name}: registered as a service provider but "
                    f"tasks/main.yml does not exist."
                )
                continue

            slug = _role_slug(role_name)
            guard_token = f"run_once_{slug}"
            guard_re = re.compile(rf"\b{re.escape(guard_token)}\b")
            content = read_text(str(main_yml))
            if not guard_re.search(content):
                violations.append(
                    f"{role_name}: registered as a service provider but "
                    f"{main_yml.relative_to(root).as_posix()} contains no "
                    f"'{guard_token}' guard. Wrap the entry tasks in either:\n"
                    f"  - include_tasks: 01_core.yml\n"
                    f"    when: {guard_token} is not defined\n"
                    f"or a `block: … when: {guard_token} is not defined` so the "
                    f"variant-aware service loader cannot include the role twice."
                )

        self.assertEqual(
            violations,
            [],
            "Service-provider roles without run_once guard:\n"
            + "\n".join(f"  - {v}" for v in violations),
        )


if __name__ == "__main__":
    unittest.main()
