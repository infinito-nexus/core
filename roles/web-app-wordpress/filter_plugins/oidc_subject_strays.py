from __future__ import annotations

import json

from ansible.errors import AnsibleFilterError

SUBJECT_META_KEY = "openid-connect-generic-subject-identity"


def oidc_subject_strays(results, subject):
    """Pair every other account with each subject-identity key that holds ``subject``.

    Args:
        results: ``results`` of the looped ``wp user meta list <ID> --keys=...
            --fields=meta_key,meta_value --format=json`` task; each ``item.item``
            is the holder (``ID``, ``user_login``) the listing ran for.
        subject: the administrator's Keycloak user id.
    Returns:
        A list of ``{"ID", "user_login", "meta_key"}``, one per key whose value is
        ``subject`` and whose name ends in the subject-identity key.
    Raises:
        AnsibleFilterError: when a listing printed no JSON list.
    """
    strays = []
    for result in results:
        holder = result["item"]["item"]
        try:
            rows = json.loads(result["stdout"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnsibleFilterError(
                f"wp user meta list printed no JSON for {holder.get('user_login')} ({exc})"
            ) from exc
        if not isinstance(rows, list):
            raise AnsibleFilterError(
                f"wp user meta list printed no JSON list for {holder.get('user_login')}"
            )
        strays.extend(
            {
                "ID": holder["ID"],
                "user_login": holder["user_login"],
                "meta_key": row["meta_key"],
            }
            for row in rows
            if str(row.get("meta_key", "")).endswith(SUBJECT_META_KEY)
            and row.get("meta_value") == subject
        )
    return strays


class FilterModule:
    """Find the subject-identity meta other accounts hold for the administrator's id."""

    def filters(self):
        return {"oidc_subject_strays": oidc_subject_strays}
