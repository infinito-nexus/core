# Simple, dependency-free "has_domain" filter.
#
# Goal:
#   Return True if the given application_id has any domain configured in `domains`.
#
# Supported `domains` shapes (best-effort):
#   - dict: {app_id: "example.org"} or {app_id: ["a.example.org", ...]} or {app_id: {"main": "..."}}
#   - str/list/dict directly (edge cases)
#
# Important:
#   No external imports, no sys.path hacks, so Ansible can always load this filter.

from __future__ import annotations

from typing import Any


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _value_has_domain(v: Any) -> bool:
    if v is None:
        return False

    if _is_nonempty_str(v):
        return True

    if isinstance(v, (list, tuple, set)):
        return any(_value_has_domain(item) for item in v)

    if isinstance(v, dict):
        return any(_value_has_domain(item) for _, item in v.items())

    return False


def has_domain(domains: Any, application_id: Any) -> bool:
    """
    Return True if `domains` contains any domain-like value for `application_id`.
    """
    app_id = "" if application_id is None else str(application_id).strip()
    if not app_id:
        return False

    if isinstance(domains, dict):
        return _value_has_domain(domains.get(app_id))

    return _value_has_domain(domains)


class FilterModule:
    def filters(self):
        return {
            "has_domain": has_domain,
        }
