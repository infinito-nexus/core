"""Which deployed role's published guide a replay should read.

``lookup('guide_role', application_id)`` picks the first invokable app the round
deployed beside ``application_id``. Invokability comes from
:func:`utils.roles.validation.invokable.list_invokable_app_ids`, so no caller
re-derives it from role-name prefixes.
"""

from __future__ import annotations

from typing import Any

from ansible.plugins.lookup import LookupBase

from plugins.lookup.deployment import running_apps
from utils.roles.validation.invokable import list_invokable_app_ids


def guide_role(application_id: str, running: list[str], invokable: list[str]) -> str:
    """Return the app whose guide is replayed, ``application_id`` when it is alone.

    Args:
        application_id: the role asking, which is skipped as its own peer.
        running: the apps this round deploys.
        invokable: every app that publishes a guide.
    """
    known = set(invokable)
    peers = [app for app in running if app != application_id and app in known]
    return peers[0] if peers else application_id


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        application_id = (
            str(terms[0]) if terms else str(vars_.get("application_id", ""))
        )
        return [
            guide_role(application_id, running_apps(vars_), list_invokable_app_ids())
        ]
