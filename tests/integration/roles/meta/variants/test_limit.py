"""Integration guard: every role's ``meta/variants.yml`` MUST declare
at most ``MAX_VARIANTS`` entries.

Rationale
---------

The matrix-deploy CLI iterates one inventory folder per variant
(see ``docs/contributing/design/variants.md``). Total deploy time grows
linearly with ``max(variant_count)`` across the primary apps, and every
extra variant doubles the surface area for cross-app/cross-round state
divergence. Capping the per-role variant count keeps the matrix
tractable: variants exist to exercise the dynamic-flag polarities,
not to enumerate every product feature.

Roles that need to express more than ``MAX_VARIANTS`` distinct
configurations SHOULD prune the matrix to the highest-value subset
(e.g. drop redundant LDAP/OIDC permutations) or move the extra
combinations into a dedicated test fixture rather than the deploy
matrix.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_VARIANTS,
    ROLE_TYPE_APPLICATION,
)
from utils.roles.type import get_role_types

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

MAX_VARIANTS = 3


def _load_yaml(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return load_yaml_any(str(path), default_if_missing=None)
    except Exception:
        return None


class TestVariantsLimit(unittest.TestCase):
    def test_variant_count_does_not_exceed_limit(self) -> None:
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            if ROLE_TYPE_APPLICATION not in get_role_types(role_dir):
                continue
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            variants = _load_yaml(variants_path)
            if not isinstance(variants, list):
                continue

            count = len(variants)
            if count > MAX_VARIANTS:
                offenders.append(
                    f"{role_name}: meta/variants.yml has {count} entries, "
                    f"but the matrix-deploy cap is {MAX_VARIANTS}. Prune "
                    f"the variant list down to {MAX_VARIANTS} or fewer."
                )

        if offenders:
            self.fail(
                f"Roles exceed the {MAX_VARIANTS}-variant matrix-deploy cap:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
