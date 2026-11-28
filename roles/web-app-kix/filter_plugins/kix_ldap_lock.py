from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Mapping

ADMINISTRATOR = "Authentication###100-Infinito-LDAP"
USER = "Authentication###200-Infinito-LDAP-User"
PAYLOAD = re.compile(r"decode_base64\('([A-Za-z0-9+/=]*)'\)")
FIELDS = {
    "host": (ADMINISTRATOR, "Config", "Host"),
    "port": (ADMINISTRATOR, "Config", "Params", "port"),
    "base_dn": (ADMINISTRATOR, "Config", "BaseDN"),
    "search_user_dn": (ADMINISTRATOR, "Config", "SearchUserDN"),
    "uid": (ADMINISTRATOR, "Config", "UID"),
    "access_attr": (ADMINISTRATOR, "Config", "AccessAttr"),
    "administrator_group_dn": (ADMINISTRATOR, "Config", "GroupDN"),
    "user_group_dn": (USER, "Config", "GroupDN"),
    "contact_sync": (ADMINISTRATOR, "Sync", 0, "Config", "ContactUserSync"),
}
MISSING = object()


def _payload(slurped) -> Mapping:
    content = slurped.get("content") if isinstance(slurped, Mapping) else None
    if not isinstance(content, str) or not content:
        return {}
    try:
        match = PAYLOAD.search(base64.b64decode(content).decode("utf-8"))
        held = json.loads(base64.b64decode(match.group(1))) if match else {}
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return {}
    return held if isinstance(held, Mapping) else {}


def _walk(node, keys):
    for key in keys:
        if isinstance(key, int):
            if not isinstance(node, list) or len(node) <= key:
                return MISSING
        elif not isinstance(node, Mapping) or key not in node:
            return MISSING
        node = node[key]
    return node


def kix_ldap_lock_fields(slurped) -> dict:
    """Return the managed LDAP fields the locked KIX config file holds.

    Args:
        slurped: the registered ``slurp`` result of the file
            ``templates/auth_ldap.conf.j2`` renders; a failed read, a
            missing payload or a malformed one yields no field.

    Returns:
        Each field of the ``ldap`` form of ``meta/forms.yml`` the file holds,
        mapped to its value; a field the file lacks is left out, and the
        bind password never appears.
    """
    held = _payload(slurped)
    fields = {}
    for field, (option, *keys) in FIELDS.items():
        value = _walk(held, [option, 0, *keys])
        if value is not MISSING:
            fields[field] = value
    return fields


class FilterModule:
    def filters(self):
        return {"kix_ldap_lock_fields": kix_ldap_lock_fields}
