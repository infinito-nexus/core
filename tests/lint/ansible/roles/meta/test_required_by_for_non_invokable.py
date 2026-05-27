"""Hard-fail when a non-invokable role does not declare any `required_by`
in its `meta/services.yml`.

Non-invokable roles (sys-ctl-*, sys-svc-*, sys-front-*, …) are
infrastructure pulled in indirectly. Declaring `required_by:
{categories: [...]}` or `required_by: {roles: [...]}` per service-entity
makes the dependency contract explicit and lets
`utils.validate.system_services` verify coverage at deploy time.

A role MAY opt out by placing `# nocheck: required-by-coverage` anywhere
in its `meta/services.yml`. The chosen categories or roles are the
maintainer's call — the test only enforces *that* the field exists, not
*which* categories/roles are listed.

All classification + meta lookups are delegated to filter plugins under
plugins/filter/.
"""

from __future__ import annotations

import unittest

from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.required_by_coverage import (
    role_has_nocheck,
    role_has_required_by,
    role_is_invokable,
)

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
NOCHECK_ID = "required-by-coverage"


class TestRequiredByForNonInvokable(unittest.TestCase):
    def test_non_invokable_roles_declare_required_by(self) -> None:
        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_id = role_dir.name
            if role_is_invokable(role_id, ROLES_DIR):
                continue
            if role_has_required_by(role_id, ROLES_DIR):
                continue
            if role_has_nocheck(role_id, NOCHECK_ID, ROLES_DIR):
                continue
            services_yml = role_dir / ROLE_FILE_META_SERVICES
            rel = services_yml.relative_to(PROJECT_ROOT).as_posix()
            offenders.append(rel if services_yml.is_file() else f"{rel} (missing)")

        if not offenders:
            return

        body = "\n".join(f"  - {p}" for p in offenders)
        self.fail(
            f"\n{len(offenders)} non-invokable role(s) without any "
            f"`required_by` in meta/services.yml:\n{body}\n\n"
            "Fix options:\n"
            "  (a) Add `required_by: {categories: [...], roles: [...]}` to "
            "the role's primary service entity in meta/services.yml. The "
            "concrete categories/roles are the maintainer's choice.\n"
            f"  (b) Opt the role out by adding `# nocheck: {NOCHECK_ID}` "
            "anywhere in its meta/services.yml."
        )


if __name__ == "__main__":
    unittest.main()
