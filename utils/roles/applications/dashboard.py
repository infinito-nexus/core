"""Target and visibility of an application's dashboard card.

A role's ``services.dashboard`` binding MAY name ``card: <key>``, a key of its
``domains.canonical`` mapping. The card, the Apps menu entry and the dashboard
tile-reachability target then point at that domain instead of the role's
primary domain.

``enabled: false`` on the same binding takes the application out of the
dashboard: no card and no Apps menu entry, and the tile-reachability targets
and the CSP frame-ancestors already follow the same flag.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean

DASHBOARD_SERVICE = "dashboard"
CARD_TARGET_KEY = "card"
ENABLED_KEY = "enabled"
ENABLED_PATH = f"services.{DASHBOARD_SERVICE}.{ENABLED_KEY}"


def card_is_displayed(application_id: str, dashboard: Any) -> bool:
    """Return whether the application's dashboard card is shown.

    Args:
        application_id: the role whose binding is read, named in the error.
        dashboard: the role's ``services.dashboard`` binding from the merged
            applications.

    Returns:
        The ``enabled`` flag, or ``True`` when the role declares no binding or
        the binding sets none.

    Raises:
        AnsibleError: the binding sets ``enabled`` to something that is not a
            boolean.
    """
    if not isinstance(dashboard, dict) or ENABLED_KEY not in dashboard:
        return True
    enabled = dashboard[ENABLED_KEY]
    try:
        return boolean(enabled, strict=True)
    except TypeError as exc:
        raise AnsibleError(
            f"{application_id}: {ENABLED_PATH} must be a boolean, got {enabled!r}"
        ) from exc


def card_target_key(application_id: str, dashboard: Any) -> str:
    """Return the ``domains.canonical`` key the dashboard card targets.

    Args:
        application_id: the role whose binding is read, named in the error.
        dashboard: the role's ``services.dashboard`` binding.

    Returns:
        The named key, or ``""`` when the binding names none and the card
        targets the primary domain.

    Raises:
        AnsibleError: the binding names something other than a non-empty
            string.
    """
    if not isinstance(dashboard, dict) or CARD_TARGET_KEY not in dashboard:
        return ""
    key = dashboard[CARD_TARGET_KEY]
    if not isinstance(key, str) or not key.strip():
        raise AnsibleError(
            f"{application_id}: services.{DASHBOARD_SERVICE}.{CARD_TARGET_KEY} "
            f"must name a domains.canonical key, got {key!r}"
        )
    return key.strip()
