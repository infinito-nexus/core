"""Filter ``gitea_auth_noop``: classify gitea auth-source idempotency errors.

    failed_when: >
      result.rc != 0 and
      not (result.stderr | gitea_auth_noop)

Returns True when the stderr of a failed ``gitea admin auth add-ldap|add-oauth``
only reports that the login source already exists; any other CLI error stays
False so the caller's failed_when still trips.
"""

from __future__ import annotations

_NOOP_MARKERS = ("login source already exists",)


def gitea_auth_noop(stderr: str | None) -> bool:
    text = (stderr or "").lower()
    return any(marker in text for marker in _NOOP_MARKERS)


class FilterModule:
    def filters(self):
        return {"gitea_auth_noop": gitea_auth_noop}
