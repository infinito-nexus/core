from __future__ import annotations

import json
from typing import Any

from ansible.errors import AnsibleFilterError

LDAP_TYPE = "2"
OAUTH2_TYPE = "6"
NULL = "NULL"
SECURITY_PROTOCOLS = {"0": "unencrypted", "1": "ldaps", "2": "starttls"}
SYNC_FLAGS = {"0": False, "1": True}
COLUMNS = (
    "id",
    "type",
    "name",
    "is_sync_enabled",
    "host",
    "port",
    "security_protocol",
    "bind_dn",
    "user_base",
    "filter",
    "admin_filter",
    "restricted_filter",
    "attribute_username",
    "attribute_name",
    "attribute_surname",
    "attribute_mail",
    "attribute_ssh_public_key",
    "attribute_avatar",
    "oauth2_provider",
    "oauth2_key",
    "open_id_connect_auto_discovery_url",
    "oauth2_scopes",
    "oauth2_group_claim_name",
    "oauth2_admin_group",
    "oauth2_restricted_group",
)
FORM_FIELDS = {
    "ldap_source": COLUMNS[3:18],
    "oauth_source": COLUMNS[18:],
}


def _scopes(value: str) -> str:
    scopes = json.loads(value)
    if not isinstance(scopes, list):
        raise AnsibleFilterError("gitea_auth_source_held: Scopes is no JSON list")
    return " ".join(str(scope) for scope in scopes)


CONVERTERS = {
    "is_sync_enabled": SYNC_FLAGS.get,
    "port": lambda value: int(value) if value.isdigit() else None,
    "security_protocol": SECURITY_PROTOCOLS.get,
    "oauth2_scopes": _scopes,
}


def _row(rows: Any, form: str, source_id: Any) -> dict[str, str] | None:
    for row in rows or []:
        record = dict(zip(COLUMNS, (str(cell) for cell in row), strict=True))
        if form == "oauth_source" and record.get("type") == OAUTH2_TYPE:
            return record
        if (
            form == "ldap_source"
            and record.get("type") == LDAP_TYPE
            and record.get("id") == str(source_id)
        ):
            return record
    return None


def gitea_auth_source_held(rows: Any, form: str, source_id: Any = "") -> dict:
    """Return the managed settings Gitea holds for the auth source a form converges.

    Args:
        rows: the rows of ``files/sql/login-source-settings.sql``.
        form: ``ldap_source`` or ``oauth_source`` of the role's meta/forms.yml.
        source_id: the id of the LDAP source the deploy keeps; the OAuth2
            source is the first one, the one the deploy updates.

    Returns:
        Each field of the form mapped to the value the source holds, in the
        form the deploy writes it; a field the source does not hold is left
        out, and no source yields an empty mapping.
    """
    if form not in FORM_FIELDS:
        raise AnsibleFilterError(f"gitea_auth_source_held: unknown form {form!r}")
    record = _row(rows, form, source_id)
    if record is None:
        return {}
    held = {}
    for field in FORM_FIELDS[form]:
        value = record.get(field)
        if value is None or value == NULL:
            continue
        converted = CONVERTERS.get(field, str)(value)
        if converted is not None:
            held[field] = converted
    return held


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"gitea_auth_source_held": gitea_auth_source_held}
