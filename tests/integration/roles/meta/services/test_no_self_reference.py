"""Integration guard: a role's own primary entity in
``meta/services.yml`` MUST NOT use the dynamic
``"{{ '<own-role-name>' in group_names }}"`` form for its
``enabled`` / ``shared`` flags. Both MUST be literal ``true``.

Rationale
---------

The role's own ``meta/services.yml`` is only loaded when the role
itself is being included — which by definition means the role IS in
the live host's ``group_names``. Asking ``'<own-role>' in group_names``
inside the role's own primary entity is therefore tautological: the
expression ALWAYS evaluates to ``true`` whenever it gets evaluated at
all. Pinning both flags to literal ``true`` avoids the dead branch
and keeps the meaning explicit ("this role is the provider; that fact
is static, not group-conditional").

For consumer references (``services.<other-key>`` in some other
role's services.yml), the dynamic form is the right shape — it
expresses "co-deploy provider X iff X is on this host". This rule
applies only to the role's own primary entity.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def _is_self_reference(value, role_name: str) -> bool:
    if not isinstance(value, str):
        return False
    if "in group_names" not in value:
        return False
    return f"'{role_name}'" in value or f'"{role_name}"' in value


class TestServicesNoSelfReference(unittest.TestCase):
    def test_primary_entity_does_not_self_reference_in_group_names(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services_path = role_dir / ROLE_FILE_META_SERVICES
            if not services_path.is_file():
                continue
            data = load_yaml_any(str(services_path), default_if_missing=None)
            if not isinstance(data, dict):
                continue

            entity_name = get_entity_name(role_name)
            entry = data.get(entity_name)
            if not isinstance(entry, dict):
                continue

            for flag in ("enabled", "shared"):
                value = entry.get(flag)
                if _is_self_reference(value, role_name):
                    offenders.append(
                        f"{role_name}: services.{entity_name}.{flag}={value!r} "
                        f"is a tautological self-reference. The role's own "
                        f"primary entity is loaded only when the role itself "
                        f"is in group_names, so the Jinja always resolves "
                        f"true. Replace with literal ``{flag}: true``."
                    )

        if offenders:
            self.fail(
                "Primary entities MUST NOT reference their own role via "
                "``in group_names`` (use literal ``true`` instead):\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
