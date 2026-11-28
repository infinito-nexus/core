"""Filter that resolves the directory full name (``cn``) of one inventory user.

{{ user | ldap_full_name(key) }}
-> "Ada Lovelace"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def ldap_full_name(user: Mapping[str, Any], key: str) -> str:
    """Return the ``cn`` OpenLDAP seeds for ``user``.

    Args:
        user: the merged user record.
        key: the user's key in the users mapping, used when it carries no name.
    """
    name = " ".join(
        str(part).strip()
        for part in (user.get("firstname"), user.get("lastname"))
        if part is not None and str(part).strip()
    )
    return str(user.get("cn") or name or key)


class FilterModule:
    def filters(self):
        return {"ldap_full_name": ldap_full_name}
