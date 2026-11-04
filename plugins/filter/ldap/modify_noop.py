"""Filter ``ldap_modify_noop``: classify ldapmodify/ldapadd idempotency errors.

    failed_when: >
      result.rc != 0 and
      not (result.stderr | ldap_modify_noop)

Returns True when the stderr of a failed ldapmodify/ldapadd only reports that
the attribute, value or entry already exists; any other LDAP error stays False
so the caller's failed_when still trips.
"""

from __future__ import annotations

_NOOP_MARKERS = (
    "type or value exists",
    "already exists",
    "duplicate value",
    "duplicate attribute value",
)


def ldap_modify_noop(stderr: str | None) -> bool:
    text = (stderr or "").lower()
    return any(marker in text for marker in _NOOP_MARKERS)


class FilterModule:
    def filters(self):
        return {"ldap_modify_noop": ldap_modify_noop}
