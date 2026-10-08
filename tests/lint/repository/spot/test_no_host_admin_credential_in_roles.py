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

from . import PROJECT_ROOT

OWNER_ROLE = "roles/user-administrator/"

_HOST_ADMIN_USER = re.compile(r"lookup\(\s*(['\"])users\1\s*,\s*(['\"])administrator\2")
_HOST_ADMIN_USER_KEY = re.compile(
    r"^\s*[a-z_]*user_key:\s*['\"]?administrator['\"]?\s*$"
)
_HOST_ADMIN_DOTTED = re.compile(r"users\.administrator\.")
_RETIRED_CREDENTIAL = re.compile(r"secrets\.credentials\.administrator_password")

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
                        f"{rel}:{number}: uses the host administrator account; "
                        f"use lookup('users', 'platform_administrator') instead"
                    )
                if _RETIRED_CREDENTIAL.search(line):
                    findings.append(
                        f"{rel}:{number}: secrets.credentials.administrator_password is "
                        f"retired; use lookup('users', 'platform_administrator') instead"
                    )

        if findings:
            self.fail(
                f"host administrator credential used in {len(findings)} place(s):\n"
                + "\n".join(f"  - {f}" for f in findings)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
