"""Target and visibility of an application's dashboard card.

A role's ``services.dashboard`` binding MAY name ``card: <key>``, a key of its
``domains.canonical`` mapping. The card, the Apps menu entry and the dashboard
tile-reachability target then point at that domain instead of the role's
primary domain.

``display: false`` on the same binding drops the card, the Apps menu entry and
the tile-reachability target.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError

DASHBOARD_SERVICE = "dashboard"
CARD_TARGET_KEY = "card"
DISPLAY_KEY = "display"
DISPLAY_PATH = f"services.{DASHBOARD_SERVICE}.{DISPLAY_KEY}"


def card_is_displayed(application_id: str, dashboard: Any) -> bool:
    """Return whether the application's dashboard card is shown.

    Args:
        application_id: the role whose binding is read, named in the error.
        dashboard: the role's ``services.dashboard`` binding from the merged
            applications.

    Returns:
        The ``display`` flag, or ``True`` when the binding sets none.

    Raises:
        AnsibleError: the binding sets ``display`` to something other than a
            bool.
    """
    if not isinstance(dashboard, dict) or DISPLAY_KEY not in dashboard:
        return True
    display = dashboard[DISPLAY_KEY]
    if not isinstance(display, bool):
        raise AnsibleError(
            f"{application_id}: {DISPLAY_PATH} must be a bool, got {display!r}"
        )
    return display


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
