"""Lint guard: every ``svc-bkp-*`` role MUST ship ``files/recover.py``
subclassing :class:`utils.recovery.base.DirectoryRecovery` and document
it in a ``## Recover`` README section.

A backup role that can only write backups is half a disaster-recovery
story: the restore path must live next to the backup path so it is
versioned, reviewed and exercised together with it (the swarm test
drill and live operators call the same script). Inheriting from the
shared base guarantees the pre-recover safety generation (the role
family's differential backup logic applied to the target) before the
``rsync --delete`` mirror, and the README must explain exactly how the
recovery works so an operator under pressure does not have to
reverse-engineer the script.
"""

from __future__ import annotations

import ast
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_ROLES_DIR = PROJECT_ROOT / "roles"
_BASE_CLASS = "DirectoryRecovery"


def _subclasses_base(recover_py: str) -> bool:
    try:
        tree = ast.parse(read_text(recover_py))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == _BASE_CLASS:
                return True
            if isinstance(base, ast.Attribute) and base.attr == _BASE_CLASS:
                return True
    return False


class TestBkpRolesHaveRecover(unittest.TestCase):
    def test_every_bkp_role_ships_recover_py_subclassing_base(self) -> None:
        bkp_roles = sorted(_ROLES_DIR.glob("svc-bkp-*"))
        self.assertTrue(bkp_roles, "no svc-bkp-* roles found")
        offenders = []
        for role in bkp_roles:
            recover = role / "files" / "recover.py"
            nocheck = role / "files" / "recover.py.nocheck"
            if nocheck.is_file():
                reason = read_text(str(nocheck)).strip()
                if (
                    reason.startswith("nocheck: bkp-recover")
                    and len(reason.splitlines()) > 1
                ):
                    continue
                offenders.append(
                    f"{role.name}: files/recover.py.nocheck must start with "
                    "'nocheck: bkp-recover' followed by the reason"
                )
                continue
            if not recover.is_file():
                offenders.append(f"{role.name}: files/recover.py missing")
            elif not _subclasses_base(str(recover)):
                offenders.append(
                    f"{role.name}: files/recover.py does not subclass "
                    f"utils.recovery.base.{_BASE_CLASS}"
                )
        if offenders:
            self.fail(
                "svc-bkp-* recover contract violations "
                f"({len(offenders)}):\n\n"
                "Every backup role must ship files/recover.py subclassing "
                f"utils.recovery.base.{_BASE_CLASS}, which runs the role's "
                "deployed backup unit before mirroring the snapshot "
                "(rsync --delete). A role whose direction has no recover "
                "counterpart opts out with files/recover.py.nocheck: first "
                "line 'nocheck: bkp-recover', followed by the reason.\n\n"
                + "\n".join(f"  - {line}" for line in offenders)
            )

    def test_every_bkp_role_documents_recover_in_readme(self) -> None:
        bkp_roles = sorted(_ROLES_DIR.glob("svc-bkp-*"))
        self.assertTrue(bkp_roles, "no svc-bkp-* roles found")
        missing = []
        for role in bkp_roles:
            readme = role / "README.md"
            if not readme.is_file() or "## Recover" not in read_text(str(readme)):
                missing.append(role.name)
        if missing:
            self.fail(
                "svc-bkp-* roles without a '## Recover' README section "
                f"({len(missing)}):\n\n"
                "Every backup role's README.md must contain a '## Recover' "
                "section explaining exactly how the recovery works: which "
                "script to run (files/recover.py), its arguments, the "
                "preconditions (e.g. stop the consuming stack first) and "
                "where the restored data and the pre-recover safety "
                "generation end up.\n\n" + "\n".join(f"  - {name}" for name in missing)
            )


if __name__ == "__main__":
    unittest.main()
