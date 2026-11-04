from __future__ import annotations

import re
import unittest

from tests.utils.personas import TEST_PERSONA_USERS
from tests.utils.role_users import declared_universe, declared_users
from utils.cache.files import iter_project_files, read_text
from utils.roles.mapping import ROLE_FILE_META_USERS

from . import PROJECT_ROOT

LOOP_HEADER = re.compile(r"^\s*(?:loop|with_items):\s*$")
LIST_ITEM = re.compile(r"^\s*-\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")
INLINE_LOOP = re.compile(r"^\s*(?:loop|with_items):\s*\[(?P<items>[^]]*)\]\s*$")
USER_KEY_PARAM = re.compile(r"^\s*[a-z_]*user_key:\s*['\"]?([A-Za-z0-9_-]+)['\"]?\s*$")
SCANNED_SUFFIXES = (".yml", ".yaml")


def _named_users(lines: list[str], index: int) -> list[str]:
    """User-key candidates a single line introduces.

    Args:
        lines: every line of the file, for looking ahead into a list block.
        index: zero-based index of the line being examined.

    Returns:
        Literal names the line acts on, before filtering to declared users.
    """
    line = lines[index]
    names: list[str] = []
    if LOOP_HEADER.match(line):
        for follow in lines[index + 1 :]:
            item = LIST_ITEM.match(follow)
            if not item:
                break
            names.append(item.group(1))
    inline = INLINE_LOOP.match(line)
    if inline:
        names += [raw.strip().strip("'\"") for raw in inline.group("items").split(",")]
    param = USER_KEY_PARAM.match(line)
    if param:
        names.append(param.group(1))
    return names


class TestLoopedUsersDeclared(unittest.TestCase):
    def test_every_user_the_role_iterates_is_declared(self):
        """
        A role that names a user as a literal it acts on, either as an item of
        a ``loop``/``with_items`` list or as a ``*user_key`` parameter, MUST
        declare that user in its own role-meta users file.

        These are the sites that provision or configure the account rather than
        merely read a field off it, so the role owns the account's existence.
        ``roles/user-root`` passing ``user_key: root`` into the ``user`` role is
        what creates root's routines; nothing in the inventory ties that to
        root's declaration unless the role states it.

        A name only counts when some role declares it as a user, so a ``loop``
        over unrelated strings is not mistaken for a user list. That matters
        because ``_compute_reserved_usernames`` turns role-name suffixes into
        reserved usernames, which would otherwise make loops over ``python`` or
        ``javascript`` look like user iteration.

        The test personas are exempt, as in ``test_lookup_users_declared``.
        """
        universe = declared_universe(PROJECT_ROOT / "roles")
        acted_on: dict[str, dict[str, str]] = {}

        for path in iter_project_files(extensions=SCANNED_SUFFIXES):
            rel = str(path).replace(f"{PROJECT_ROOT}/", "")
            parts = rel.split("/")
            if len(parts) < 2 or parts[0] != "roles":
                continue
            lines = read_text(str(path)).splitlines()
            for index, line in enumerate(lines):
                if line.lstrip().startswith("#"):
                    continue
                for name in _named_users(lines, index):
                    if name in universe and name not in TEST_PERSONA_USERS:
                        acted_on.setdefault(parts[1], {}).setdefault(
                            name, f"{rel}:{index + 1}"
                        )

        findings: list[str] = []
        for role, keys in sorted(acted_on.items()):
            declared = declared_users(PROJECT_ROOT / "roles" / role)
            findings.extend(
                f"- roles/{role}/{ROLE_FILE_META_USERS} does not declare "
                f"'{user_key}', iterated at {keys[user_key]}"
                for user_key in sorted(set(keys) - declared)
            )

        if findings:
            self.fail(
                "Every user a role iterates or passes as a user_key must be "
                f"declared in that role's {ROLE_FILE_META_USERS}:\n"
                + "\n".join(findings)
            )


if __name__ == "__main__":
    unittest.main()
