"""Lint: a `web-*` role MUST NOT declare another `web-*` role as a hard
Ansible meta dependency.

Cross-`web-*` includes belong in the variant-aware service registry:

  1. The provider role marks its primary entity `shared: true` in
     `meta/services.yml` (Discourse pattern), declares
     `enabled: true|false` next to it, and conforms to the
     service-role schema (`tasks/01_core.yml` first, `run_once`
     guard in `tasks/main.yml`).
  2. The consumer role declares
     `services.<provider-entity>.enabled: true` and `shared: true`
     in its own `meta/services.yml` (always-on) or
     `meta/variants.yml` (round-specific).

Putting another `web-*` role in `meta/main.yml.dependencies` makes it
mandatory for every deploy of the consumer role and bypasses the
variant-aware planner. That couples otherwise independent roles and
violates / expectations around per-role inclusion.
"""

import unittest
from typing import Any

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN

from . import PROJECT_ROOT


def _extract_dependency_role_names(raw: Any) -> list[str]:
    """Normalize meta/main.yml `dependencies:` into a flat list of role
    names. Mirrors the loader at
    `cli/meta/roles/applications/resolution/combined/role_introspection.py`.
    """
    if not raw:
        return []
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for entry in raw:
        if isinstance(entry, str):
            name = entry.strip()
            if name:
                out.append(name)
        elif isinstance(entry, dict):
            name = entry.get("role") or entry.get("name")
            if isinstance(name, str) and name.strip():
                out.append(name.strip())
    return out


def _entity_from_role(role: str) -> str:
    """Strip the leading `web-app-` / `web-svc-` prefix to derive the
    entity name used as the service-registry key."""
    for prefix in ("web-app-", "web-svc-"):
        if role.startswith(prefix):
            return role[len(prefix) :]
    return role


def _fix_hint(consumer: str, offender: str) -> str:
    offender_entity = _entity_from_role(offender)
    return (
        f"  Fix:\n"
        f"    1. In roles/{offender}/meta/services.yml mark the\n"
        f"       primary entity `{offender_entity}:` with `shared: true`\n"
        f"       and `enabled: true|false`, and ensure it conforms to the\n"
        f"       service-role schema (tasks/01_core.yml first,\n"
        f"       run_once guard in tasks/main.yml).\n"
        f"    2. In roles/{consumer}/meta/services.yml (always-on) or\n"
        f"       roles/{consumer}/meta/variants.yml (round-specific) declare:\n"
        f"         services:\n"
        f"           {offender_entity}:\n"
        f"             enabled: true\n"
        f"             shared: true\n"
        f"       The variant-aware deploy planner then auto-includes\n"
        f"       {offender} in the round's deploy plan.\n"
        f"    3. Remove `{offender}` from roles/{consumer}/meta/main.yml.dependencies."
    )


class TestWebRoleNoWebDependency(unittest.TestCase):
    """`web-*` MUST NOT depend on another `web-*` via meta/main.yml."""

    def test_no_web_role_in_web_role_dependencies(self):
        root = PROJECT_ROOT
        roles_dir = root / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        violations: list[str] = []
        for role_path in sorted(roles_dir.iterdir()):
            if not (role_path.is_dir() and role_path.name.startswith("web-")):
                continue

            meta_main = role_path / ROLE_FILE_META_MAIN
            if not meta_main.is_file():
                continue

            data = load_yaml(meta_main, default_if_missing={}) or {}
            if not isinstance(data, dict):
                continue

            deps = _extract_dependency_role_names(data.get("dependencies"))
            offending_deps = [d for d in deps if d.startswith("web-")]
            if offending_deps:
                rel = meta_main.relative_to(root).as_posix()
                violations.extend(
                    f"{rel}: web-* role '{role_path.name}' declares "
                    f"web-* role '{offender}' as an Ansible meta dependency.\n"
                    + _fix_hint(role_path.name, offender)
                    for offender in offending_deps
                )

        self.assertEqual(
            violations,
            [],
            "\n\n".join(
                [
                    "web-* roles MUST NOT hard-depend on other web-* roles via "
                    "meta/main.yml. Use the variant-aware service registry "
                    "(meta/services.yml shared: true + services.<X>.enabled: true) "
                    "instead. Offenders:",
                    *violations,
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
