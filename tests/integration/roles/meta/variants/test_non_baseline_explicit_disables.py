"""Integration guard: for every dynamic service-key declared in a
role's ``meta/services.yml`` (i.e. ``enabled`` is a Jinja
``{{ ... }}`` expression) that variant 0 pins to literal ``true`` in
``meta/variants.yml``, every non-baseline variant (index > 0) MUST
explicitly pin the same key to either literal ``enabled: true`` (to
re-enable it) or to literal ``enabled: false`` AND ``shared: false``
(to disable it).

Why
---

`utils.cache.applications._build_application_defaults` returns each
role's base config (assembled `meta/<topic>.yml` payload, no
variants overlay). The matrix-deploy CLI bakes variant N as an
inventory-level `applications.<app>` override, which then deep-merges
on top of those defaults. For dynamic service-keys declared in
``meta/services.yml`` the base value is the Jinja expression, but
``variants.yml`` pins them to a literal boolean. The non-baseline
override only sees the variant's own services map, so any key
variant 0 pins to ``true`` and variant N omits stays at variant 0's
literal value via deep-merge.

The auth-only special case of this rule already lives in
[test_auth_isolation.py](./test_auth_isolation.py); this file
generalises it to every dynamic flag the role's variant matrix
toggles to ``true`` in the baseline.

Variant-only keys (declared only in ``meta/variants.yml`` and not in
``meta/services.yml``) are out of scope. Defaults do not carry them,
so omitting them from a non-baseline variant cannot leak them in.

Statically-enabled keys (``services.<k>.enabled`` declared as the
literal ``true`` in ``meta/services.yml``) are exempt: pinning them
``false`` in a variant would only break the role's own deploy
without trimming any closure (the resolver pulls the static dep in
regardless). The auth-isolation rule applies the same exemption.

Exemption
---------

Place ``# nocheck: variants-explicit-disables`` on the same line as
the variant's leading ``- services:`` (or on the line immediately
above) to skip the check for that single variant entry. Reserve the
exemption for variants whose contract genuinely tolerates the
inherited flags (e.g. a multisite variant whose enabled set is a
true superset of variant 0).
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "variants-explicit-disables"


def _is_enabled_true(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get("enabled") is True


def _is_literal_false(value: object) -> bool:
    return value is False


def _entry_pinned_false(entry: object) -> bool:
    return (
        isinstance(entry, dict)
        and _is_literal_false(entry.get("enabled"))
        and _is_literal_false(entry.get("shared"))
    )


def _dynamic_enabled_keys_in_services_yml(services_file: Path) -> set[str]:
    try:
        services_raw = load_yaml_any(str(services_file), default_if_missing={})
    except Exception:
        return set()
    if not isinstance(services_raw, dict):
        return set()
    out: set[str] = set()
    for key, entry in services_raw.items():
        if not (isinstance(key, str) and isinstance(entry, dict)):
            continue
        enabled = entry.get("enabled")
        if isinstance(enabled, str) and "in group_names" in enabled:
            out.add(key)
    return out


def _variant_header_line_numbers(variants_file: Path) -> dict[int, int]:
    lines = read_text(str(variants_file)).splitlines()
    out: dict[int, int] = {}
    variant_index = -1
    for idx, raw in enumerate(lines):
        if raw.startswith("- "):
            variant_index += 1
            out[variant_index] = idx + 1
    return out


def _baseline_enabled_keys(baseline: dict, in_scope: set[str]) -> set[str]:
    services = baseline.get("services") or {}
    if not isinstance(services, dict):
        return set()
    return {
        key
        for key, entry in services.items()
        if isinstance(key, str) and key in in_scope and _is_enabled_true(entry)
    }


class TestVariantsExplicitDisables(unittest.TestCase):
    def test_non_baseline_variants_explicitly_disable_baseline_only_keys(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            variants_file = role_dir / ROLE_FILE_META_VARIANTS
            if not variants_file.is_file():
                continue

            try:
                variants_raw = load_yaml_any(str(variants_file), default_if_missing=[])
            except Exception as exc:
                offenders.append(f"{role_name}: meta/variants.yml parse error: {exc}")
                continue
            if not isinstance(variants_raw, list) or len(variants_raw) < 2:
                continue

            baseline = variants_raw[0] if isinstance(variants_raw[0], dict) else {}
            dynamic_scope = _dynamic_enabled_keys_in_services_yml(
                role_dir / ROLE_FILE_META_SERVICES
            )
            baseline_keys = _baseline_enabled_keys(baseline, dynamic_scope)
            if not baseline_keys:
                continue

            header_lines = _variant_header_line_numbers(variants_file)
            text_lines = read_text(str(variants_file)).splitlines()

            for index in range(1, len(variants_raw)):
                variant = variants_raw[index]
                if not isinstance(variant, dict):
                    continue

                header_line = header_lines.get(index)
                if header_line is not None and is_suppressed_at(
                    text_lines, header_line, _RULE
                ):
                    continue

                services = variant.get("services") or {}
                if not isinstance(services, dict):
                    services = {}

                missing: list[str] = []
                for key in sorted(baseline_keys):
                    entry = services.get(key)
                    if _is_enabled_true(entry):
                        continue
                    if _entry_pinned_false(entry):
                        continue
                    missing.append(key)

                if missing:
                    offenders.append(
                        f"{role_name}: variant[{index}] inherits "
                        f"{', '.join(missing)} from variant 0 via deep-merge. "
                        f"Pin each key to `enabled: false, shared: false` "
                        f"(or re-enable it explicitly), otherwise the "
                        f"matrix-deploy round silently runs with the "
                        f"inherited flag(s) on. Mark the variant with "
                        f"``# nocheck: {_RULE}`` only when the inheritance "
                        f"is intentional."
                    )

        if offenders:
            self.fail(
                f"meta/variants.yml non-baseline variants must explicitly "
                f"pin baseline-only dynamic keys to literal false "
                f"({_RULE}, {len(offenders)} offender(s)):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
