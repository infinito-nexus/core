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

The marker exempts that service key in every variant of the file. A hook is
resolver-only for the role, not for one round of it, and repeating the same
marker at each occurrence states one fact several times.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

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


_KEY = re.compile(r"^\s*(?P<key>[A-Za-z_][\w.-]*):")


def _exempt_keys(lines: list[str]) -> set[str]:
    """Return the service keys the file exempts from this rule.

    Exception: the marker is read straight off the text. The line-number scan
    this used to go through recorded nothing for some variant shapes, so the
    rule reported keys that could not be exempted at all.

    Args:
        lines: the variants file, split into lines.
    """
    exempt: set[str] = set()
    for index, line in enumerate(lines):
        if f"nocheck: {_RULE}" not in line:
            continue
        named = _KEY.match(line)
        if named:
            exempt.add(named.group("key"))
            continue
        for follower in lines[index + 1 :]:
            if not follower.strip():
                break
            named = _KEY.match(follower)
            if named:
                exempt.add(named.group("key"))
            break
    return exempt


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

            variants_text_lines = read_text(str(variants_file)).splitlines()

            exempt = _exempt_keys(variants_text_lines)

            for index, variant in enumerate(variants_raw):
                if not isinstance(variant, dict):
                    continue
                variant_services = variant.get("services")
                if not isinstance(variant_services, dict):
                    continue
                for key in variant_services:
                    if not isinstance(key, str):
                        continue
                    if key in declared_keys or key in exempt:
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
