"""Lint guard: the administrator step of the listed roles MUST create a
missing administrator, not only realign an existing one.

An app installed before its administrator login was introduced has no such
account. A step that only realigns then ends in "no ... user named" or
"user ... does not exist" on every deploy of that install, while a fresh
install passes, so no test round catches it.

Each entry names the file the role's administrator step runs and the call
that creates the account. A rewrite that drops the create path fails the
first test. The second test flags a further script in these roles that can
end in such a failure, so a new realign step lands with its create path or
in this list.

The list is explicit rather than a scan of every role: ``web-app-gitlab``
realigns ``root``, which every GitLab install has, and would be flagged by
the same failure text without being wrong.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_ROLES_DIR = PROJECT_ROOT / "roles"

ADMIN_STEPS = {
    "web-app-joomla": ("tasks/07_reset_admin_password.yml", "user:add"),
    "web-app-listmonk": ("files/sql/realign_admin_credential.sql", "INSERT INTO users"),
    "web-app-matomo": ("files/php/converge_superuser_password.php", "insertSuperuser("),
    "web-app-mediawiki": (
        "files/shell/realign_admin_password.sh",
        "createAndPromote --bureaucrat --sysop --email",
    ),
    "web-app-suitecrm": (
        "files/php/realign_admin_password.php",
        "insertAdministrator(",
    ),
    "web-app-wordpress": ("files/php/realign_admin_password.php", "wp_insert_user("),
}

_ABSENT_ACCOUNT = re.compile(
    r"no [\w ]*?(?:user|account|administrator|superuser) named|user [^\n]*does not exist",
    re.IGNORECASE,
)


def _role_scripts(role: str):
    trees = tuple(_ROLES_DIR / role / tree for tree in ("files", "tasks"))
    for raw in sorted(iter_project_files()):
        path = Path(raw)
        if any(tree in path.parents for tree in trees) and "playwright" not in path.parts:
            yield path


class TestAdminStepCreatesMissingAdmin(unittest.TestCase):
    def test_every_admin_step_keeps_its_create_path(self) -> None:
        offenders = []
        for role, (step, marker) in sorted(ADMIN_STEPS.items()):
            path = _ROLES_DIR / role / step
            if not path.is_file():
                offenders.append(
                    f"{role}: {step} is gone; point the entry at the new step"
                )
            elif marker not in read_text(str(path)):
                offenders.append(f"{role}: {step} no longer calls {marker!r}")
        self.assertFalse(
            offenders,
            "these administrator steps only realign an existing account, so an "
            "install without it fails on every deploy; create it next to the "
            "existing administrators:\n  " + "\n  ".join(offenders),
        )

    def test_no_other_script_of_these_roles_ends_on_an_absent_account(self) -> None:
        offenders = []
        for role, (step, _) in sorted(ADMIN_STEPS.items()):
            for path in _role_scripts(role):
                relative = path.relative_to(_ROLES_DIR / role).as_posix()
                if relative == step:
                    continue
                try:
                    text = read_text(str(path))
                except UnicodeDecodeError:
                    continue
                if _ABSENT_ACCOUNT.search(text):
                    offenders.append(f"{role}/{relative}")
        self.assertFalse(
            offenders,
            "these scripts can end on an absent account; give them a create "
            "path and list them in ADMIN_STEPS:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
