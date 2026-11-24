from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping


def ldap_user_dn(user: Mapping[str, Any], id_attribute: str, users_dn: str) -> str:
    """Args:
        user: the merged user record; its ``username`` is the RDN value.
        id_attribute: RDN and login attribute of a user entry.
        users_dn: DN of the users OU.

    Returns:
        The DN of the directory entry of ``user``, named by its login.
    """
    return f"{id_attribute}={user['username']},{users_dn}"


class FilterModule:
    def filters(self):
        return {"ldap_user_dn": ldap_user_dn}
