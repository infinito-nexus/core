"""Integration guard: every ``services.yml`` flag that resolves via
the dynamic ``"{{ '<role>' in group_names }}"`` form MUST be exercised
by ``meta/variants.yml`` — at least one variant entry pinning the
flag to literal ``true``, AND at least one pinning it to literal
``false``.

Rationale
---------

The matrix-deploy CLI iterates the per-role variant list (see
``docs/contributing/artefact/files/role/variants.md``) and produces
one inventory folder per entry. A flag declared as dynamic in
``services.yml`` only takes its boolean shape once the inventory
templar resolves it against the host's ``group_names``. Without
explicit variant overrides on both sides, the matrix only ever
exercises one branch — the role can ship for years with the
``false`` (or ``true``) path effectively dead.

This test makes that coverage explicit: the role's own
``meta/variants.yml`` MUST contain, for each dynamic
``(service_key, flag)`` pair, at least one variant overriding the
flag to ``true`` and one overriding it to ``false``. Pairs may share
variants — a single entry may pin multiple unrelated services true
while pinning others false; the test only checks that the union of
all variants covers both polarities for every dynamic flag.

For databases the same rule reduces to coverage of ``shared``: the
DB-consumer ``enabled`` flag stays literal ``true`` (with
``# nocheck: dynamic-flag``), so only ``shared`` is dynamic and needs
the two-polarity coverage.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_TYPE_APPLICATION,
)
from utils.roles.type import get_role_types

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


_RULE = "dynamic-flag"


def _is_dynamic_flag(value) -> bool:
    return isinstance(value, str) and "in group_names" in value


def _suppressed_top_level_keys(file_path: Path) -> set[str]:
    """Return the set of top-level service keys whose preceding comment
    block carries a ``# nocheck: dynamic-flag`` marker (mirrors
    ``tests.integration.roles.meta.services.test_dynamic_flags``)."""
    exceptions: set[str] = set()
    pending = False
    for raw_line in read_text(str(file_path)).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            if line_has_rule(raw_line, _RULE):
                pending = True
            continue
        if not stripped:
            pending = False
            continue
        is_top_level = not raw_line.startswith((" ", "\t"))
        if pending and is_top_level and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key:
                exceptions.add(key)
        pending = False
    return exceptions


def _dynamic_pairs(services: dict, suppressed: set[str]) -> list[tuple[str, str]]:
    """Return ``[(service_key, flag_name), ...]`` for every flag whose
    value is a Jinja string carrying ``in group_names``."""
    pairs: list[tuple[str, str]] = []
    for key, entry in services.items():
        if not isinstance(entry, dict) or key in suppressed:
            continue
        pairs.extend(
            (key, flag)
            for flag in ("enabled", "shared")
            if _is_dynamic_flag(entry.get(flag))
        )
    return pairs


def _load_yaml(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return load_yaml_any(str(path), default_if_missing=None)
    except Exception:
        return None


def _variant_overrides_for(variant: dict, service_key: str, flag: str) -> object:
    """Return the literal override value for ``services.<key>.<flag>``
    in ``variant``, or a sentinel ``MISSING`` if not overridden."""
    services = variant.get("services") if isinstance(variant, dict) else None
    if not isinstance(services, dict):
        return _MISSING
    entry = services.get(service_key)
    if not isinstance(entry, dict):
        return _MISSING
    if flag not in entry:
        return _MISSING
    return entry[flag]


_MISSING = object()


class TestVariantsCoverage(unittest.TestCase):
    def test_every_dynamic_flag_has_true_and_false_variant(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            if ROLE_TYPE_APPLICATION not in get_role_types(role_dir):
                continue
            services_path = role_dir / ROLE_FILE_META_SERVICES
            services = _load_yaml(services_path)
            if not isinstance(services, dict):
                continue

            pairs = _dynamic_pairs(services, _suppressed_top_level_keys(services_path))
            if not pairs:
                continue

            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list):
                offenders.append(
                    f"{role_name}: services.yml declares {len(pairs)} dynamic "
                    f"flag(s) but {variants_path.relative_to(PROJECT_ROOT)} "
                    f"is missing or not a YAML list. Add a list with at least "
                    f"two entries that pin each dynamic flag to ``true`` and "
                    f"``false`` respectively."
                )
                continue

            normalised_variants = [v if isinstance(v, dict) else {} for v in variants]

            for service_key, flag in sorted(pairs):
                seen_true = False
                seen_false = False
                for variant in normalised_variants:
                    override = _variant_overrides_for(variant, service_key, flag)
                    if override is True:
                        seen_true = True
                    elif override is False:
                        seen_false = True
                if not seen_true:
                    offenders.append(
                        f"{role_name}: services.{service_key}.{flag} is "
                        f"dynamic but no variant in meta/variants.yml pins "
                        f"it to ``true``. Add an entry with "
                        f"``services.{service_key}.{flag}: true``."
                    )
                if not seen_false:
                    offenders.append(
                        f"{role_name}: services.{service_key}.{flag} is "
                        f"dynamic but no variant in meta/variants.yml pins "
                        f"it to ``false``. Add an entry with "
                        f"``services.{service_key}.{flag}: false``."
                    )

        if offenders:
            self.fail(
                "Dynamic-flag variant coverage is incomplete (every "
                "``in group_names`` flag needs a true-pinning AND a "
                "false-pinning variant entry):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
