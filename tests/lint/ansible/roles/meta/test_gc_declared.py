from __future__ import annotations

import unittest

from utils.roles.gc import gc_findings
from utils.roles.validation.invokable import (
    _get_invokable_paths,
    _is_role_invokable,
)

from . import PROJECT_ROOT


class TestGcDeclared(unittest.TestCase):
    def test_every_role_declares_a_consistent_gc(self) -> None:
        invokable_paths = _get_invokable_paths()
        offenders: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if not role_dir.is_dir() or role_dir.name.startswith((".", "_")):
                continue
            required = _is_role_invokable(role_dir.name, invokable_paths)
            offenders.extend(
                f"  - {role_dir.name}: {finding}"
                for finding in gc_findings(role_dir, required=required)
            )
        if offenders:
            self.fail(
                "Roles whose meta/services.yml.<primary_entity>.gc is missing or "
                "inconsistent (see docs/contributing/artefact/files/role/gc.sh.md):\n"
                + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
