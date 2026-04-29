"""Lint guards for the post-req-008/009/010 role meta layout.

Failure modes covered:
  * Any role retains ``schema/main.yml``, ``users/main.yml`` or
    ``config/main.yml`` (req-008 file-move ACs).
  * Any source file references those legacy paths (req-008 path-rewrite AC).
  * ``meta/main.yml`` carries ``run_after`` or ``lifecycle`` (req-010
    location AC).
  * ``meta/services.yml.<entity>.lifecycle`` carries an out-of-allowlist
    value (req-010 schema AC).
  * ``meta/services.yml.<entity>.ports.{local,public}`` is a bare int
    instead of a category-keyed map (req-009 schema AC).
  * Any host-bound port collides with another (single int + relay span set;
    req-009 port-collision AC).
  * Any ``meta/services.yml.<entity>.ports`` value falls outside its
    ``PORT_BANDS.<scope>.<category>`` range (req-009 band-membership AC).
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
ROLES_DIR = REPO_ROOT / "roles"

ALLOWED_LIFECYCLES = {
    "planned",
    "pre-alpha",
    "alpha",
    "beta",
    "stable",
    "deprecated",
}

# Roles whose `local.http` port is allowed to live outside the documented
# band (req-009 explicit allow-list).
LEGACY_PORT_ALLOWLIST = {
    ("web-app-bigbluebutton", "bigbluebutton", "local", "http"): {48087},
}


def _load_yaml(path: Path):
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return None
    return yaml.safe_load(text)


class TestNoLegacyRoleDirs(unittest.TestCase):
    def test_no_legacy_dirs(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            for legacy in ("config", "schema", "users"):
                legacy_path = role_dir / legacy
                if legacy_path.is_dir():
                    offenders.append(str(legacy_path.relative_to(REPO_ROOT)))
        if offenders:
            self.fail(
                "Legacy role directories present (must move under meta/, "
                "per req-008):\n" + "\n".join(f"  - {p}" for p in offenders)
            )


class TestNoLegacyPathReferences(unittest.TestCase):
    """Repository-wide grep guard for the old path strings (req-008)."""

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

    EXEMPT_FILES: set[Path] = {
        REPO_ROOT / "tasks" / "utils" / "migrate_meta_layout.py",
    }

    def test_no_legacy_path_strings(self):
        offenders: list[str] = []
        for sub in self.SCAN_DIRS:
            root = REPO_ROOT / sub
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                str_path = str(path)
                if any(frag in str_path for frag in self.SKIP_FRAGMENTS):
                    continue
                if path in self.EXEMPT_FILES:
                    continue
                if path.suffix not in {
                    ".py",
                    ".yml",
                    ".yaml",
                    ".j2",
                    ".jinja",
                    ".jinja2",
                }:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError):
                    continue
                for token in self.LEGACY_TOKENS:
                    if token in text:
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)} contains {token!r}"
                        )
                        break
        if offenders:
            self.fail(
                "Legacy path tokens present (req-008 forbids these):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestMetaMainHasNoRunAfterOrLifecycle(unittest.TestCase):
    def test_no_run_after_or_lifecycle_in_meta_main(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            meta_main = role_dir / "meta" / "main.yml"
            data = _load_yaml(meta_main)
            if not isinstance(data, dict):
                continue
            galaxy_info = data.get("galaxy_info")
            if not isinstance(galaxy_info, dict):
                continue
            if "run_after" in galaxy_info:
                offenders.append(
                    f"{meta_main.relative_to(REPO_ROOT)}: galaxy_info.run_after"
                )
            if "lifecycle" in galaxy_info:
                offenders.append(
                    f"{meta_main.relative_to(REPO_ROOT)}: galaxy_info.lifecycle"
                )
        if offenders:
            self.fail(
                "run_after/lifecycle must live on the role's primary entity "
                "in meta/services.yml (req-010):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestLifecycleAllowedValues(unittest.TestCase):
    def test_lifecycle_values_in_allowed_set(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            services = _load_yaml(role_dir / "meta" / "services.yml")
            if not isinstance(services, dict):
                continue
            for entity_name, entity in services.items():
                if not isinstance(entity, dict):
                    continue
                lifecycle = entity.get("lifecycle")
                if lifecycle is None:
                    continue
                if isinstance(lifecycle, str):
                    value = lifecycle.strip().lower()
                else:
                    value = ""
                if value not in ALLOWED_LIFECYCLES:
                    offenders.append(
                        f"{role_dir.name}/{entity_name}: lifecycle={lifecycle!r}"
                    )
        if offenders:
            self.fail(
                "lifecycle must be one of "
                f"{sorted(ALLOWED_LIFECYCLES)} (req-010):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestPortShape(unittest.TestCase):
    def test_local_and_public_ports_are_category_keyed_maps(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            services = _load_yaml(role_dir / "meta" / "services.yml")
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
                "ports.{local,public} must be category-keyed maps "
                "(req-009):\n" + "\n".join(f"  - {o}" for o in offenders)
            )


class TestHostBoundPortCollisions(unittest.TestCase):
    # Per req-009 explicit allow-list: legacy BBB http port 48087 lives
    # inside the BBB relay range (40000-49999) historically. Same role
    # owning both ends of the collision is acceptable for this specific
    # documented exception.
    _SAME_ROLE_LEGACY_OVERLAPS = {
        ("web-app-bigbluebutton", 48087),
    }

    def test_no_host_bound_port_collisions(self):
        from utils.meta.scan import host_bound_port_set

        host_bound = host_bound_port_set()
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
            pretty = ", ".join(
                f"{role}/{entity} {scope}.{cat}" for role, entity, scope, cat in owners
            )
            clashes.append(f"port {port}: {pretty}")
        if clashes:
            self.fail(
                "Host-bound port collisions detected (req-009):\n"
                + "\n".join(f"  - {c}" for c in clashes)
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
                "PORT_BANDS membership / shape violation (req-009):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


class TestNoComposeWrapperInVariants(unittest.TestCase):
    """Per req-008 the file root of meta/services.yml IS the services map.
    Variant overrides in meta/variants.yml MUST follow the same shape: top
    keys are server / services / rbac / volumes / credentials / users,
    NEVER `compose:` (which silently no-ops because the loader doesn't
    look there)."""

    def test_no_compose_wrapper_in_variants(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            variants_path = role_dir / "meta" / "variants.yml"
            if not variants_path.is_file():
                continue
            text = variants_path.read_text(encoding="utf-8")
            try:
                docs = yaml.safe_load(text)
            except yaml.YAMLError:
                continue
            if not isinstance(docs, list):
                continue
            for index, entry in enumerate(docs):
                if isinstance(entry, dict) and "compose" in entry:
                    offenders.append(
                        f"{variants_path.relative_to(REPO_ROOT)} variant "
                        f"{index} contains a `compose:` wrapper (expected "
                        f"top-level `services:` / `server:` / `volumes:`)."
                    )
        if offenders:
            self.fail(
                "meta/variants.yml MUST NOT use a `compose:` wrapper "
                "(req-008):\n" + "\n".join(f"  - {o}" for o in offenders)
            )


class TestRunAfterNotEmpty(unittest.TestCase):
    def test_no_empty_run_after_lists(self):
        offenders: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            services = _load_yaml(role_dir / "meta" / "services.yml")
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
                "constraint exists (req-010):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":
    unittest.main()
