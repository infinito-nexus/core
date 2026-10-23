"""Forbid an application role from using the host administrator account at all.

``users.administrator`` is the host account: ``roles/user-administrator`` hashes
its password into the OS user, and ``files/administrator`` grants that user
``ALL=(ALL) ALL`` without ``NOPASSWD``, so the value is password-authenticated
sudo. It is also ``ROTATION_EXEMPT``, because rotating it would lock the deploy
out of its own host.

An application that reads its credential therefore turns one app-level leak
into host root, and the credential cannot be rotated to recover.
``platform_administrator`` is the single source for application admin accounts
instead: it is SSO-capable, carries no host account, and rotates like any other
user.

Both spellings count. The account is reachable as ``lookup('users',
'administrator')`` and, through the config lookup, as the dotted path
``lookup('config', application_id, 'users.administrator.email')``; five roles
used the second form, so a rule written for the first alone misses them.

No field of it is exempt, not only the password. Reading ``.email``,
``.firstname`` or ``.uid`` stamps the host operator's identity onto an
application's admin account, and an identity provider that matches on e-mail
then resolves the application admin to the host operator, which is the coupling
this split exists to remove. Mixing the two is also how an account ends up
built from both at once, with one user's address and another's login name.

The retired ``secrets.credentials.administrator_password`` is forbidden too: it
was a per-role copy of the same concept, and nothing declares it any more.

Scope: every git-tracked file under ``roles/`` except ``roles/user-administrator``,
which owns the host account.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import iter_non_ignored_files, read_text
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

OWNER_ROLE = "roles/user-administrator/"

_GENERAL_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"


def admin_user_keys() -> tuple[str, str]:
    """Return the host administrator key and the platform administrator key.

    Returns:
        ``IAM_HOST_ADMIN_USER_KEY`` and ``IAM_PLATFORM_ADMIN_USER_KEY`` from
        the global variables, so this rule matches the keys the roles actually
        resolve instead of a second copy of their spelling.
    """
    general = load_yaml(str(_GENERAL_VARS))
    return (
        str(general["IAM_HOST_ADMIN_USER_KEY"]),
        str(general["IAM_PLATFORM_ADMIN_USER_KEY"]),
    )


HOST_ADMIN, PLATFORM_ADMIN = admin_user_keys()

_HOST_ADMIN_USER = re.compile(
    rf"lookup\(\s*(['\"])users\1\s*,\s*(['\"]){re.escape(HOST_ADMIN)}\2"
)
_HOST_ADMIN_USER_KEY = re.compile(
    rf"^\s*[a-z_]*user_key:\s*['\"]?{re.escape(HOST_ADMIN)}['\"]?\s*$",
    re.IGNORECASE,
)
_HOST_ADMIN_DOTTED = re.compile(rf"users\.{re.escape(HOST_ADMIN)}\.")
_RETIRED_CREDENTIAL = re.compile(
    rf"secrets\.credentials\.{re.escape(HOST_ADMIN)}_password"
)

_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".js", ".sh", ".sql")


class TestNoHostAdminCredentialInRoles(unittest.TestCase):
    def test_roles_use_the_platform_administrator(self) -> None:
        findings: list[str] = []

        for path in iter_non_ignored_files(extensions=_SUFFIXES):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            if not rel.startswith("roles/") or rel.startswith(OWNER_ROLE):
                continue
            for number, line in enumerate(read_text(str(path)).splitlines(), 1):
                if (
                    _HOST_ADMIN_USER.search(line)
                    or _HOST_ADMIN_USER_KEY.match(line)
                    or _HOST_ADMIN_DOTTED.search(line)
                ):
                    findings.append(
                        f"{rel}:{number}: uses the {HOST_ADMIN} account; read "
                        f"IAM_PLATFORM_ADMIN_USER_KEY ({PLATFORM_ADMIN}) instead"
                    )
                if _RETIRED_CREDENTIAL.search(line):
                    findings.append(
                        f"{rel}:{number}: secrets.credentials.{HOST_ADMIN}_password is "
                        f"retired; read IAM_PLATFORM_ADMIN_USER_KEY ({PLATFORM_ADMIN}) instead"
                    )

        if findings:
            self.fail(
                f"host administrator credential used in {len(findings)} place(s):\n"
                + "\n".join(f"  - {f}" for f in findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
