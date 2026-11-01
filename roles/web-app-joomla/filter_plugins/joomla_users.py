from __future__ import annotations

import re
import unicodedata

from ansible.errors import AnsibleFilterError

_BORDER = re.compile(r"^ *-+(?: +-+)* *$")
_HEADER = ["ID", "Username", "Name", "Email", "Blocked", "Groups"]
_ADMIN_GROUP = "Super Users"
_ZERO_WIDTH = frozenset({"Mn", "Me", "Cf"})
_DOUBLE_WIDTH = frozenset({"W", "F"})
_DUPLICATE_USERNAME = "The username already exists!"
_DUPLICATE_EMAIL = "The email address already exists!"


def _width(char: str) -> int:
    """Return the terminal columns ``char`` takes in a Symfony table.

    Args:
        char: one code point.

    Returns:
        0 for combining marks and format characters, 2 for East Asian wide
        and fullwidth characters, 1 otherwise.
    """
    if unicodedata.combining(char) or unicodedata.category(char) in _ZERO_WIDTH:
        return 0
    return 2 if unicodedata.east_asian_width(char) in _DOUBLE_WIDTH else 1


def _cut(line: str, spans: list[tuple[int, int]]) -> list[str]:
    """Split a table row into the cells under the border's dash runs.

    Args:
        line: one row of the table.
        spans: ``[start, end)`` display columns of every dash run.

    Returns:
        The stripped text of every cell, in column order.
    """
    cells: list[list[str]] = [[] for _ in spans]
    column = 0
    for char in line:
        for index, (start, end) in enumerate(spans):
            if start <= column < end:
                cells[index].append(char)
                break
        column += _width(char)
    return ["".join(cell).strip() for cell in cells]


def joomla_user_accounts(output) -> list[dict]:
    """Read the accounts out of the table ``cli/joomla.php user:list`` prints.

    The table is cut along its ``---`` border, not along whitespace, because a
    name may hold spaces and the group column lists ``Registered, Super Users``.
    The border is cut in display columns, not code points: Symfony pads every
    cell to the display width of the widest one, so a CJK name takes two
    columns per character and a decomposed accent takes none.

    Args:
        output: stdout of ``user:list``.

    Returns:
        One ``{login, email, admin}`` per listed account, ``admin`` being
        membership in the Super Users group.
    """
    lines = output.splitlines() if isinstance(output, str) else []
    borders = [index for index, line in enumerate(lines) if _BORDER.match(line)]
    if len(borders) < 3:
        raise AnsibleFilterError("user:list printed no account table")

    spans = [match.span() for match in re.finditer(r"-+", lines[borders[0]])]

    header = _cut(lines[borders[0] + 1], spans)
    if header != _HEADER:
        raise AnsibleFilterError(
            f"user:list printed the columns {header}, expected {_HEADER}"
        )

    accounts = []
    for line in lines[borders[1] + 1 : borders[-1]]:
        if not line.strip() or _BORDER.match(line):
            continue
        row = dict(zip(_HEADER, _cut(line, spans), strict=True))
        accounts.append(
            {
                "login": row["Username"],
                "email": row["Email"],
                "admin": _ADMIN_GROUP
                in [group.strip() for group in row["Groups"].split(",")],
            }
        )
    return accounts


def joomla_user_add_conflict(output, login: str, email: str) -> str:
    """Explain a ``user:add`` refusal caused by an account ``user:list`` hides.

    ``user:list`` inner-joins every account with its user groups, so an account
    that belongs to no group never reached the plan that chose to add.

    Args:
        output: stdout and stderr of ``user:add``.
        login: username that was added.
        email: email that was added.

    Returns:
        The failure message for a username or email Joomla already holds, an
        empty string for any other refusal.
    """
    text = output if isinstance(output, str) else ""
    if _DUPLICATE_USERNAME in text:
        return (
            f"the Joomla account '{login}' (in any letter case) already exists but "
            "belongs to no user group, so user:list does not show it; add it to "
            "Super Users in Users > Manage or rename it, then redeploy"
        )
    if _DUPLICATE_EMAIL in text:
        return (
            f"a Joomla account without any user group already holds '{email}', so "
            "user:list does not show it; give that account a user group or change "
            "its email in Users > Manage, then redeploy"
        )
    return ""


class FilterModule:
    def filters(self):
        return {
            "joomla_user_accounts": joomla_user_accounts,
            "joomla_user_add_conflict": joomla_user_add_conflict,
        }
