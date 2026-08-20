"""Lint guards for the role meta layout.

Failure modes covered:
  * Any role retains ``schema/main.yml``, ``users/main.yml`` or
    ``config/main.yml``.
  * Any source file references those legacy paths.
  * ``meta/main.yml`` carries ``run_after`` or ``lifecycle``.
  * ``meta/services.yml.<entity>.lifecycle`` carries a value outside the
    linear axis in
    ``docs/contributing/design/role/services/lifecycle.md``
    (``ALLOWED_LIFECYCLES``).
  * ``meta/services.yml.<entity>.ports.{local,public}`` is a bare int
    instead of a category-keyed map.
  * Any host-bound port collides with another (single int + relay span set;
    port-collision AC).
  * Any ``meta/services.yml.<entity>.ports`` value falls outside its
    ``PORT_BANDS.<scope>.<category>`` range.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

import yaml

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

ALLOWED_LIFECYCLES = {
    "planned",
    "pre-alpha",
    "alpha",
    "beta",
    "rc",
    "stable",
    "maintenance",
    "deprecated",
    "eol",
}

LEGACY_PORT_ALLOWLIST = {
    ("web-app-bigbluebutton", "bigbluebutton", "local", "http"): {48087},
}


def _load_yaml(path: Path):
    if not path.is_file():
        return None
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    return load_yaml_str(text)


class TestNoLegacyRoleDirs(unittest.TestCase):
    def test_no_legacy_dirs(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            for legacy in ("config", "schema", "users"):
                legacy_path = role_dir / legacy
                if legacy_path.is_dir():
                    offenders.append(str(legacy_path.relative_to(PROJECT_ROOT)))
        if offenders:
            self.fail(
                "Legacy role directories present (must move under meta/):\n"
                + "\n".join(f"  - {p}" for p in offenders)
            )


class TestNoLegacyPathReferences(unittest.TestCase):
    """Repository-wide grep guard for the old path strings."""

    LEGACY_TOKENS = (
        "schema/main.yml",
        "users/main.yml",
        "config/main.yml",
        "compose.services.",
        "compose.volumes.",
    )

    SCAN_DIRS = (
        "plugins",
        "utils",
        "cli",
        "roles",
        "scripts",
        "filter_plugins",
        "lookup_plugins",
    )

    SKIP_FRAGMENTS = (
        "/__pycache__/",
        "/.git/",
        "/node_modules/",
        "/.venv/",
        "/.cache/",
    )

    EXEMPT_FILES: ClassVar[set[Path]] = {
        PROJECT_ROOT / "tasks" / "utils" / "migrate_meta_layout.py",
    }

    def test_no_legacy_path_strings(self):
        offenders: list[str] = []
        scan_prefixes = tuple(f"{sub}/" for sub in self.SCAN_DIRS)
        scan_suffixes = (".py", ".yml", ".yaml", ".j2", ".jinja", ".jinja2")
        for path_str in iter_project_files(extensions=scan_suffixes):
            path = Path(path_str)
            try:
                rel_str = path.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if not rel_str.startswith(scan_prefixes):
                continue
            if any(frag in path_str for frag in self.SKIP_FRAGMENTS):
                continue
            if path in self.EXEMPT_FILES:
                continue
            try:
                text = read_text(path_str)
            except (UnicodeDecodeError, PermissionError):
                continue
            for token in self.LEGACY_TOKENS:
                if token in text:
                    offenders.append(f"{rel_str} contains {token!r}")
                    break
        if offenders:
            self.fail(
                "Legacy path tokens present:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestMetaMainHasNoRunAfterOrLifecycle(unittest.TestCase):
    def test_no_run_after_or_lifecycle_in_meta_main(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            meta_main = role_dir / ROLE_FILE_META_MAIN
            data = _load_yaml(meta_main)
            if not isinstance(data, dict):
                continue
            galaxy_info = data.get("galaxy_info")
            if not isinstance(galaxy_info, dict):
                continue
            if "run_after" in galaxy_info:
                offenders.append(
                    f"{meta_main.relative_to(PROJECT_ROOT)}: galaxy_info.run_after"
                )
            if "lifecycle" in galaxy_info:
                offenders.append(
                    f"{meta_main.relative_to(PROJECT_ROOT)}: galaxy_info.lifecycle"
                )
        if offenders:
            self.fail(
                "run_after/lifecycle must live on the role's primary entity "
                "in meta/services.yml:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


class TestLifecycleAllowedValues(unittest.TestCase):
    def test_lifecycle_values_in_allowed_set(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict):
                continue
            for entity_name, entity in services.items():
                if not isinstance(entity, dict):
                    continue
                lifecycle = entity.get("lifecycle")
                if lifecycle is None:
                    continue
                value = lifecycle.strip().lower() if isinstance(lifecycle, str) else ""
                if value not in ALLOWED_LIFECYCLES:
                    offenders.append(
                        f"{role_dir.name}/{entity_name}: lifecycle={lifecycle!r}"
                    )
        if offenders:
            self.fail(
                "lifecycle must be one of "
                f"{sorted(ALLOWED_LIFECYCLES)}:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestPortShape(unittest.TestCase):
    def test_local_and_public_ports_are_category_keyed_maps(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict):
                continue
            for entity_name, entity in services.items():
                if not isinstance(entity, dict):
                    continue
                ports = entity.get("ports")
                if not isinstance(ports, dict):
                    continue
                for scope_name in ("local", "public"):
                    scope = ports.get(scope_name)
                    if scope is None:
                        continue
                    if not isinstance(scope, dict):
                        offenders.append(
                            f"{role_dir.name}/{entity_name}.ports."
                            f"{scope_name}: expected map, got "
                            f"{type(scope).__name__}"
                        )
        if offenders:
            self.fail(
                "ports.{local,public} must be category-keyed maps:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestHostBoundPortCollisions(unittest.TestCase):
    _SAME_ROLE_LEGACY_OVERLAPS: ClassVar[set[tuple[str, int]]] = {
        ("web-app-bigbluebutton", 48087),
    }

    @staticmethod
    def _provider_alternative_groups() -> list[set[str]]:
        """Role sets that are runtime-exclusive alternatives for one service
        key: the role that ``provides`` the key plus every role whose primary
        entity ``covers`` it (e.g. the mail providers — only the active
        ``MAIL_PROVIDER`` publishes the ports; the other renders without
        them). Derived from the self-declared registry, no role names here."""
        from utils.roles.applications.services.registry import (
            build_service_registry_from_roles_dir,
        )

        registry = build_service_registry_from_roles_dir(ROLES_DIR)
        provider_of: dict[str, str] = {}
        coverers: dict[str, set[str]] = {}
        for key, entry in registry.items():
            if "canonical" in entry:
                continue
            role = entry.get("role", "")
            provider_of[key] = role
            for covered in entry.get("covers", []) or []:
                coverers.setdefault(covered, set()).add(role)
        return [
            {provider_of[key], *roles}
            for key, roles in coverers.items()
            if key in provider_of
        ]

    def test_no_host_bound_port_collisions(self):
        from utils.meta.scan import host_bound_port_set

        host_bound = host_bound_port_set()
        alternative_groups = self._provider_alternative_groups()
        clashes: list[str] = []
        for port, owners in sorted(host_bound.items()):
            if len(owners) <= 1:
                continue
            roles_holding = {role for role, _e, _s, _c in owners}
            if (
                len(roles_holding) == 1
                and (next(iter(roles_holding)), port) in self._SAME_ROLE_LEGACY_OVERLAPS
            ):
                continue
            if any(roles_holding <= group for group in alternative_groups):
                continue
            pretty = ", ".join(
                f"{role}/{entity} {scope}.{cat}" for role, entity, scope, cat in owners
            )
            clashes.append(f"port {port}: {pretty}")
        if clashes:
            self.fail(
                "Host-bound port collisions detected:\n"
                + "\n".join(f"  - {c}" for c in clashes)
                + "\n\nFix: pick a free port via "
                + "`infinito meta ports suggest --scope <local|public> "
                + "--category <http|oauth2|websocket|...> --count 1` "
                + "and update the role's meta/services.yml."
            )


class TestPortBandMembership(unittest.TestCase):
    def test_each_port_falls_within_its_band(self):
        from utils.meta.port_bands import lookup_band
        from utils.meta.scan import iter_port_assignments, iter_relay_ranges

        offenders: list[str] = []
        for role, entity, scope, category, port in iter_port_assignments():
            allowlist = LEGACY_PORT_ALLOWLIST.get(
                (role, entity, scope, category), set()
            )
            if port in allowlist:
                continue
            band = lookup_band(scope, category)
            if band is None:
                offenders.append(
                    f"{role}/{entity}.ports.{scope}.{category}={port}: "
                    f"no PORT_BANDS entry"
                )
                continue
            band_start, band_end = band
            if not (band_start <= port <= band_end):
                offenders.append(
                    f"{role}/{entity}.ports.{scope}.{category}={port} is "
                    f"outside PORT_BANDS.{scope}.{category}"
                    f"=({band_start}-{band_end})"
                )
        for role, entity, start, end in iter_relay_ranges():
            band = lookup_band("public", "relay")
            if band is None:
                offenders.append(
                    f"{role}/{entity}.ports.public.relay={start}-{end}: "
                    f"no PORT_BANDS entry"
                )
                continue
            if start > end:
                offenders.append(
                    f"{role}/{entity}.ports.public.relay={start}-{end}: start >= end"
                )
            band_start, band_end = band
            if start < band_start or end > band_end:
                offenders.append(
                    f"{role}/{entity}.ports.public.relay={start}-{end} is "
                    f"outside PORT_BANDS.public.relay"
                    f"=({band_start}-{band_end})"
                )
        if offenders:
            self.fail(
                "PORT_BANDS membership / shape violation:\n"
                + "\n".join(f"  - {o}" for o in offenders)
                + "\n\nFix: pick an in-band port via "
                + "`infinito meta ports suggest --scope <local|public> "
                + "--category <http|oauth2|websocket|...> --count 1`. "
                + "If the band itself is exhausted, extend "
                + "`PORT_BANDS.<scope>.<category>.end` in "
                + "group_vars/all/08_networks.yml."
            )


class TestPortBandsDisjoint(unittest.TestCase):
    """PORT_BANDS within a single scope MUST be pairwise disjoint, otherwise
    a port could legitimately belong to two categories at once and the
    suggester / band-membership lint would silently route it to the
    wrong category. Cross-scope overlaps (e.g. local.http=8001-8099 and
    public.https=...) are intentional and not checked here."""

    def test_no_overlapping_bands_in_same_scope(self):
        from utils.meta.port_bands import load_port_bands

        offenders: list[str] = []
        for scope, scope_block in (load_port_bands() or {}).items():
            if not isinstance(scope_block, dict):
                continue
            ranges: list[tuple[str, int, int]] = []
            for category, entry in scope_block.items():
                if not isinstance(entry, dict):
                    continue
                start = entry.get("start")
                end = entry.get("end")
                if not isinstance(start, int) or not isinstance(end, int):
                    continue
                if start > end:
                    offenders.append(
                        f"PORT_BANDS.{scope}.{category}: start ({start}) > end ({end})"
                    )
                    continue
                ranges.append((category, start, end))

            ranges.sort(key=lambda r: (r[1], r[2]))
            for i in range(len(ranges)):
                cat_a, start_a, end_a = ranges[i]
                for j in range(i + 1, len(ranges)):
                    cat_b, start_b, end_b = ranges[j]
                    if start_b > end_a:
                        break
                    overlap_start = max(start_a, start_b)
                    overlap_end = min(end_a, end_b)
                    offenders.append(
                        f"PORT_BANDS.{scope}.{cat_a}={start_a}-{end_a} overlaps "
                        f"PORT_BANDS.{scope}.{cat_b}={start_b}-{end_b} on "
                        f"{overlap_start}-{overlap_end}"
                    )

        if offenders:
            self.fail(
                "PORT_BANDS overlap detected:\n"
                + "\n".join(f"  - {o}" for o in offenders)
                + "\n\nFix: shrink one of the overlapping ranges in "
                + "group_vars/all/08_networks.yml so each port belongs to "
                + "at most one (scope, category) pair."
            )


class TestNoComposeWrapperInVariants(unittest.TestCase):
    """The file root of meta/services.yml IS the services map.
    Variant overrides in meta/variants.yml MUST follow the same shape: top
    keys are server / services / rbac / volumes / credentials / users,
    NEVER `compose:` (which silently no-ops because the loader doesn't
    look there)."""

    def test_no_compose_wrapper_in_variants(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            if not variants_path.is_file():
                continue
            try:
                text = read_text(str(variants_path))
            except UnicodeDecodeError:
                continue
            try:
                docs = load_yaml_str(text)
            except yaml.YAMLError:
                continue
            if not isinstance(docs, list):
                continue
            for index, entry in enumerate(docs):
                if isinstance(entry, dict) and "compose" in entry:
                    offenders.append(
                        f"{variants_path.relative_to(PROJECT_ROOT)} variant "
                        f"{index} contains a `compose:` wrapper (expected "
                        f"top-level `services:` / `server:` / `volumes:`)."
                    )
        if offenders:
            self.fail(
                "meta/variants.yml MUST NOT use a `compose:` wrapper:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestRunAfterNotEmpty(unittest.TestCase):
    def test_no_empty_run_after_lists(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict):
                continue
            for entity_name, entity in services.items():
                if not isinstance(entity, dict):
                    continue
                run_after = entity.get("run_after")
                if isinstance(run_after, list) and not run_after:
                    offenders.append(f"{role_dir.name}/{entity_name}")
        if offenders:
            self.fail(
                "run_after must be omitted (not empty list) when no ordering "
                "constraint exists:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
