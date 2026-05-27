"""Integration guard: every service key referenced under ``services:``
in a role's `meta/variants.yml` MUST exist as a top-level key in the
same role's `meta/services.yml`.

Why
---

The matrix-deploy CLI deep-merges each variant onto the role's
`meta/services.yml` to produce one effective `applications.<role>`
config per variant entry. Keys that exist in `variants.yml` but NOT
in `services.yml` survive the merge as dead config — at best a typo
that silently does nothing, at worst a stale reference to a service
that was renamed or removed (and now silently fails to flip its
flags). Either way the variant promises coverage for a service the
role does not actually declare.

This test catches that drift early. The check is intentionally
asymmetric: extra keys in `services.yml` (services declared but not
overridden by any variant) are fine and tracked by
[test_variants_coverage.py](./test_variants_coverage.py); only the
opposite direction (variant overrides → services declared) is what
this guard enforces.

Exemption
---------

Place ``# nocheck: variants-services-match`` on the same line as the
variant's service-key declaration (or on the line immediately above)
when the key is a resolver-only matrix hook with no real consumer
contract in ``meta/services.yml`` — typical for invokable
infrastructure roles whose variant entries pin the round's companion
topology via service-key flags the resolver maps to provider roles.
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

_RULE = "variants-services-match"


def _load_yaml(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return load_yaml_any(str(path), default_if_missing=None)
    except Exception:
        return None


def _variant_service_key_line_numbers(
    variants_file: Path,
) -> dict[tuple[int, str], int]:
    """Map ``(variant_index, service_key)`` -> 1-based line number for
    every top-level service key declared under a variant's ``services:``
    mapping. Variant index advances at every top-level list item (lines
    that begin with ``- ``)."""
    lines = read_text(str(variants_file)).splitlines()
    out: dict[tuple[int, str], int] = {}

    variant_index = -1
    stack: list[tuple[int, str]] = []

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if raw.startswith("- "):
            variant_index += 1
            stack = []
            after_dash = raw[2:]
            indent = 0
            line_for_key = after_dash
        else:
            indent = len(raw) - len(raw.lstrip(" "))
            line_for_key = stripped

        while stack and stack[-1][0] >= indent:
            stack.pop()

        if ":" not in line_for_key:
            continue
        key = line_for_key.split(":", 1)[0].strip()
        if not key:
            continue
        stack.append((indent, key))

        # Only record direct children of `services:` (depth == 2 in the
        # variant subtree).
        path_keys = [k for _, k in stack]
        if len(path_keys) == 2 and path_keys[0] == "services":
            out[(variant_index, path_keys[1])] = idx + 1

    return out


class TestVariantsServicesMatch(unittest.TestCase):
    def test_variants_only_reference_services_declared_in_services_yml(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services = _load_yaml(role_dir / ROLE_FILE_META_SERVICES)
            if not isinstance(services, dict):
                continue
            declared_keys = {k for k in services if isinstance(k, str)}

            variants_file = role_dir / ROLE_FILE_META_VARIANTS
            variants_raw = _load_yaml(variants_file)
            if not isinstance(variants_raw, list):
                continue

            line_numbers = _variant_service_key_line_numbers(variants_file)
            variants_text_lines = read_text(str(variants_file)).splitlines()

            for index, variant in enumerate(variants_raw):
                if not isinstance(variant, dict):
                    continue
                variant_services = variant.get("services")
                if not isinstance(variant_services, dict):
                    continue
                for key in variant_services:
                    if not isinstance(key, str):
                        continue
                    if key in declared_keys:
                        continue

                    line_no = line_numbers.get((index, key))
                    if line_no is not None and is_suppressed_at(
                        variants_text_lines, line_no, _RULE
                    ):
                        continue

                    offenders.append(
                        f"{role_name}: variants.yml[{index}].services.{key} "
                        f"is not declared as a top-level key in "
                        f"meta/services.yml. Either add ``{key}:`` to "
                        f"services.yml, drop the override from this variant "
                        f"entry, or mark the line with "
                        f"``# nocheck: {_RULE}`` for legitimate "
                        f"resolver-only matrix hooks."
                    )

        if offenders:
            self.fail(
                "variants.yml references services not declared in "
                "services.yml:\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
