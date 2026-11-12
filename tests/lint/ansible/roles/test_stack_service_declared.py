from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
)
from utils.roles.required_by_coverage import role_has_nocheck

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"
STACK_KEY = "stack"
OPENRESTY_KEY = "openresty"
NOCHECK_ID = "openresty-vhost"
STACK_ROLE_PREFIX = "sys-stk-"
COMPOSE_CATEGORIES = ("web-app-", "web-svc-")
_INCLUDE = r"^\s*(?:-\s+|name:\s*)[\"']?sys-stk-({roles})[\"']?\s*$"
STACK_INCLUDE_RE = re.compile(
    _INCLUDE.format(roles="full|backend|front-proxy"), re.MULTILINE
)
VHOST_INCLUDE_RE = re.compile(_INCLUDE.format(roles="full|front-proxy"), re.MULTILINE)
_ENTRY = (
    r"^\s*name:\s*[\"']?svc-stack[\"']?\s*\n"
    r"\s*tasks_from:\s*[\"']?consumer({entries})\.yml[\"']?\s*$"
)
STACK_ENTRY_RE = re.compile(_ENTRY.format(entries="|/front|/back"), re.MULTILINE)
VHOST_ENTRY_RE = re.compile(_ENTRY.format(entries="|/front"), re.MULTILINE)


def _role_dirs() -> list[Path]:
    return sorted(
        p
        for p in ROLES_DIR.iterdir()
        if p.is_dir() and not p.name.startswith(STACK_ROLE_PREFIX)
    )


def _includes(role_dir: Path, pattern: re.Pattern[str]) -> bool:
    return any(
        pattern.search(read_text(str(path))) for path in role_dir.glob("tasks/**/*.yml")
    )


def _has_compose_project(role_dir: Path) -> bool:
    return (
        role_dir.name.startswith(COMPOSE_CATEGORIES)
        and (role_dir / ROLE_FILE_TEMPL_COMPOSE).is_file()
    )


def _serves_canonical_domain(role_dir: Path) -> bool:
    domains = load_yaml_any(
        str(role_dir / ROLE_FILE_META_DOMAINS), default_if_missing={}
    )
    return isinstance(domains, dict) and bool(domains.get("canonical"))


def _declares(role_dir: Path, key: str) -> bool:
    services: Any = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    entry = services.get(key) if isinstance(services, dict) else None
    return (
        isinstance(entry, dict)
        and entry.get("enabled") is True
        and entry.get("shared") is True
    )


def stack_offenders() -> list[str]:
    return [
        role_dir.name
        for role_dir in _role_dirs()
        if (
            _has_compose_project(role_dir)
            or _includes(role_dir, STACK_INCLUDE_RE)
            or _includes(role_dir, STACK_ENTRY_RE)
        )
        and not _declares(role_dir, STACK_KEY)
    ]


def openresty_offenders() -> list[str]:
    return [
        role_dir.name
        for role_dir in _role_dirs()
        if (
            _serves_canonical_domain(role_dir)
            or _includes(role_dir, VHOST_INCLUDE_RE)
            or _includes(role_dir, VHOST_ENTRY_RE)
        )
        and not _declares(role_dir, OPENRESTY_KEY)
        and not role_has_nocheck(role_dir.name, NOCHECK_ID, ROLES_DIR)
    ]


class TestStackServiceDeclared(unittest.TestCase):
    def test_one_role_provides_the_stack_service(self) -> None:
        entry = build_service_registry_from_roles_dir(ROLES_DIR).get(STACK_KEY)
        self.assertIsNotNone(entry, "no role provides the 'stack' service")
        self.assertTrue(
            entry["enabled"] and entry["shared"],
            f"{entry['role']}: the 'stack' primary entity MUST be enabled and shared",
        )

    def test_stack_consumers_declare_stack(self) -> None:
        offenders = stack_offenders()
        self.assertEqual(
            offenders,
            [],
            f"\n{len(offenders)} role(s) with a compose project or a stack role "
            "include lack 'stack: {enabled: true, shared: true}' in "
            "meta/services.yml:\n" + "\n".join(f"  - {name}" for name in offenders),
        )

    def test_vhost_roles_declare_openresty(self) -> None:
        offenders = openresty_offenders()
        self.assertEqual(
            offenders,
            [],
            f"\n{len(offenders)} role(s) serving a vhost lack 'openresty: "
            "{enabled: true, shared: true}' in meta/services.yml (or "
            f"'# nocheck: {NOCHECK_ID} <reason>' when the stack does not "
            "serve the domain):\n" + "\n".join(f"  - {name}" for name in offenders),
        )

    def test_entry_patterns_tell_the_vhost_entries_apart(self) -> None:
        include = "- include_role:\n    name: svc-stack\n    tasks_from: {}\n"
        for entry, serves in (
            ("consumer.yml", True),
            ('"consumer/front.yml"', True),
            ("consumer/back.yml", False),
        ):
            text = include.format(entry)
            self.assertTrue(STACK_ENTRY_RE.search(text), entry)
            self.assertEqual(bool(VHOST_ENTRY_RE.search(text)), serves, entry)
        for other in ("deferred_probe.yml", "consumer/other.yml", "main.yml"):
            self.assertIsNone(STACK_ENTRY_RE.search(include.format(other)), other)


if __name__ == "__main__":
    unittest.main()
