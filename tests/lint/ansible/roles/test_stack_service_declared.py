from __future__ import annotations

import importlib.util
import re
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache.files import iter_non_ignored_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.mapping import (
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_META_SERVER,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
)
from utils.roles.required_by_coverage import role_has_nocheck

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
TASKS_DIR = PROJECT_ROOT / "tasks"
LEGACY_STACK_ROLES = ("sys-stk-full", "sys-stk-backend", "sys-stk-front-proxy")
LEGACY_NAME_RE = re.compile(r"sys[-_]stk[-_](?:full|backend|front[-_]proxy)")
LEGACY_NAME_EXEMPT = (
    "locale/",
    "CHANGELOG.md",
    "packaging/debian/changelog",
    "packaging/fedora/infinito-nexus.spec",
    "docs/requirements/",
    Path(__file__).resolve().relative_to(PROJECT_ROOT).as_posix(),
    "tests/unit/python/cli/meta/roles/services/called/test_called.py",
)
PER_VHOST_VARS = (
    "webserver_proxy_service_key",
    "webserver_vhost_flavour",
    "webserver_websocket_location",
    "webserver_client_max_body_size",
    "webserver_extra_configuration",
    "webserver_location_extra_configuration",
)
_PER_VHOST = "|".join(PER_VHOST_VARS)
PER_VHOST_NAME_RE = re.compile(rf"\b(?:{_PER_VHOST})\b")
PER_VHOST_KEY_RE = re.compile(rf"^\s*(?:{_PER_VHOST})\s*:")
PER_VHOST_OUTPUT_RE = re.compile(rf"(?:^\s*|['\"])(?:{_PER_VHOST})['\"]?\s*:")
STACK_KEY = "stack"
OPENRESTY_KEY = "openresty"
NOCHECK_ID = "openresty-vhost"
COMPOSE_CATEGORIES = ("web-app-", "web-svc-")
_ENTRY = (
    r"^\s*name:\s*[\"']?svc-stack[\"']?\s*\n"
    r"\s*tasks_from:\s*[\"']?consumer({entries})\.yml[\"']?\s*$"
)
STACK_ENTRY_RE = re.compile(_ENTRY.format(entries="|/front|/back"), re.MULTILINE)
VHOST_ENTRY_RE = re.compile(_ENTRY.format(entries="|/front"), re.MULTILINE)


def _role_dirs() -> list[Path]:
    return sorted(p for p in ROLES_DIR.iterdir() if p.is_dir())


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
        if (_has_compose_project(role_dir) or _includes(role_dir, STACK_ENTRY_RE))
        and not _declares(role_dir, STACK_KEY)
    ]


def openresty_offenders() -> list[str]:
    return [
        role_dir.name
        for role_dir in _role_dirs()
        if (_serves_canonical_domain(role_dir) or _includes(role_dir, VHOST_ENTRY_RE))
        and not _declares(role_dir, OPENRESTY_KEY)
        and not role_has_nocheck(role_dir.name, NOCHECK_ID, ROLES_DIR)
    ]


def _lines(path: Path) -> list[str]:
    try:
        return read_text(str(path)).splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def legacy_stack_mentions(exempt: tuple[str, ...] = LEGACY_NAME_EXEMPT) -> list[str]:
    """Args:
        exempt: repository paths, a trailing slash marking a directory, whose
            lines may keep naming a removed stack role: locale/ holds the
            gettext catalogs that i18n-extract regenerates, CHANGELOG.md and
            the two packaging changelogs record past releases,
            docs/requirements/ records past requirements, this lint carries
            the names in its patterns, and test_called.py feeds a removed
            role's task header to the verifier.

    Returns:
        ``path:line`` of every other line of the repository, pulled custom
        roles included, that names a removed stack role or one of its
        variables.
    """
    hits = []
    for name in iter_non_ignored_files():
        path = Path(name)
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(exempt):
            continue
        hits.extend(
            f"{rel}:{number}"
            for number, line in enumerate(_lines(path), 1)
            if LEGACY_NAME_RE.search(line)
        )
    return sorted(hits)


def _vhost_param_hit(role: str, path: Path, line: str) -> bool:
    if path == ROLES_DIR / "svc-stack" / "tasks" / "proxy" / "vhost.yml":
        return bool(PER_VHOST_NAME_RE.search(PER_VHOST_OUTPUT_RE.sub("", line)))
    if role == "svc-stack":
        return bool(PER_VHOST_NAME_RE.search(line))
    return bool(PER_VHOST_KEY_RE.match(line))


def call_site_vhost_params() -> list[str]:
    """Returns:
    ``path:line`` of every task line that sets a per-vhost parameter outside
    the svc-stack vhost writer, and of every svc-stack task line that reads
    one instead of the role's meta.
    """
    files = [
        (role_dir.name, path)
        for role_dir in _role_dirs()
        for path in sorted(role_dir.glob("tasks/**/*.yml"))
    ] + [("", path) for path in sorted(TASKS_DIR.glob("**/*.yml"))]
    return [
        f"{path.relative_to(ROLES_DIR.parent)}:{number}"
        for role, path in files
        for number, line in enumerate(_lines(path), 1)
        if _vhost_param_hit(role, path, line)
    ]


def _stack_vhosts():
    path = ROLES_DIR / "svc-stack" / "filter_plugins" / "stack_vhosts.py"
    spec = importlib.util.spec_from_file_location("stack_vhosts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stack_vhosts


def _domain_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [d for item in value.values() for d in _domain_list(item)]
    if isinstance(value, list):
        return [d for item in value for d in _domain_list(item)]
    return []


def _maybe_enabled(entry: Any) -> dict:
    """Args:
    entry: one declared vhost; a templated ``enabled`` counts as on.
    """
    vhost = dict(entry or {})
    enabled = vhost.get("enabled")
    if isinstance(enabled, str) and "{{" in enabled:
        del vhost["enabled"]
    return vhost


def uncovered_vhost_domains() -> list[str]:
    """Returns:
    ``role: domain`` for every canonical domain of a role that declares
    openresty but whose server.vhosts serves no vhost for that domain,
    resolved through the svc-stack stack_vhosts filter.
    """
    stack_vhosts = _stack_vhosts()
    missing: list[str] = []
    for role_dir in _role_dirs():
        if not _declares(role_dir, OPENRESTY_KEY):
            continue
        domains = load_yaml_any(
            str(role_dir / ROLE_FILE_META_DOMAINS), default_if_missing={}
        )
        canonical = domains.get("canonical") if isinstance(domains, dict) else None
        wanted = _domain_list(canonical)
        if not wanted:
            continue
        server = load_yaml_any(
            str(role_dir / ROLE_FILE_META_SERVER), default_if_missing={}
        )
        vhosts = (server.get("vhosts") if isinstance(server, dict) else None) or {}
        declared = {key: _maybe_enabled(entry) for key, entry in vhosts.items()}
        try:
            served = {
                entry["domain"]
                for entry in stack_vhosts(declared, wanted[0], canonical, [])
            }
        except AnsibleFilterError as error:
            missing.append(f"{role_dir.name}: {error}")
            continue
        missing.extend(f"{role_dir.name}: {d}" for d in wanted if d not in served)
    return missing


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
            f"\n{len(offenders)} role(s) with a compose project or a svc-stack "
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

    def test_no_file_names_a_removed_stack_role(self) -> None:
        hits = legacy_stack_mentions()
        self.assertEqual(
            hits,
            [],
            f"\n{len(hits)} line(s) name a removed stack role "
            f"({', '.join(LEGACY_STACK_ROLES)}). Move the caller to svc-stack: "
            "include it with tasks_from: consumer.yml (consumer/front.yml or "
            "consumer/back.yml for one half), declare stack and openresty in "
            "meta/services.yml, put the per-vhost parameters under "
            "server.vhosts in meta/server.yml, and read stack_batch_consumer "
            "where sys_stk_full_application_id was read:\n"
            + "\n".join(f"  - {hit}" for hit in hits),
        )

    def test_every_exempt_path_exists(self) -> None:
        for rel in LEGACY_NAME_EXEMPT:
            with self.subTest(path=rel):
                self.assertTrue((PROJECT_ROOT / rel).exists(), rel)

    def test_legacy_name_pattern_spares_other_stack_roles(self) -> None:
        for named in (
            *LEGACY_STACK_ROLES,
            "roles/sys-stk-front-proxy/tasks/vhost.yml",
            "{{ sys_stk_full_application_id }}",
        ):
            self.assertTrue(LEGACY_NAME_RE.search(named), named)
        for other in ("name: sys-stk-front-base", "name: svc-stack"):
            self.assertIsNone(LEGACY_NAME_RE.search(other), other)

    def test_vhost_parameters_come_only_from_meta(self) -> None:
        hits = call_site_vhost_params()
        self.assertEqual(
            hits,
            [],
            f"\n{len(hits)} task line(s) pass or read a per-vhost parameter "
            f"({', '.join(PER_VHOST_VARS)}); declare it under server.vhosts in "
            "meta/server.yml, which svc-stack reads:\n"
            + "\n".join(f"  - {hit}" for hit in hits),
        )

    def test_vhost_parameter_patterns_tell_outputs_from_reads(self) -> None:
        self.assertTrue(PER_VHOST_KEY_RE.match('    webserver_vhost_flavour: "basic"'))
        self.assertIsNone(PER_VHOST_KEY_RE.match("    flavour: basic"))
        for output in (
            '    webserver_websocket_location: "{{ front_proxy_websocket_location }}"',
            "| combine({'webserver_location_extra_configuration': x})",
        ):
            self.assertIsNone(
                PER_VHOST_NAME_RE.search(PER_VHOST_OUTPUT_RE.sub("", output)), output
            )
        read = "    x: \"{{ webserver_client_max_body_size | default('1m') }}\""
        self.assertTrue(PER_VHOST_NAME_RE.search(PER_VHOST_OUTPUT_RE.sub("", read)))

    def test_every_canonical_domain_has_vhost_data(self) -> None:
        missing = uncovered_vhost_domains()
        self.assertEqual(
            missing,
            [],
            f"\n{len(missing)} canonical domain(s) of a role that declares "
            "openresty have no vhost in meta/server.yml; add a server.vhosts "
            "entry keyed by the domains.canonical key, or name the domain "
            "under 'domain' or 'domains':\n"
            + "\n".join(f"  - {entry}" for entry in missing),
        )


if __name__ == "__main__":
    unittest.main()
