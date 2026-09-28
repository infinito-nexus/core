"""Which deployed role's published guide a replay should read.

``lookup('guide_role', application_id)`` names exactly one role, never a list:
the replay brings up a machine per role, so a round that deployed twenty of
them still replays one guide.

The role comes from ``APP_ID``, which the deploy workflow sets to the row's
app and :mod:`cli.administration.deploy.development.deploy.run` forwards into
the container. A round that carries no such name, or one naming a role that
publishes no guide, draws an invokable peer at random instead, so a local
round covers a different guide each time rather than always the first one the
inventory happens to list. Invokability comes from
:func:`utils.roles.validation.invokable.list_invokable_app_ids`, so no caller
re-derives it from role-name prefixes.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from ansible.plugins.lookup import LookupBase

from plugins.lookup.deployment import running_apps
from utils.roles.validation.invokable import list_invokable_app_ids

ENV_VAR = "APP_ID"


def guide_role(
    application_id: str,
    running: list[str],
    invokable: list[str],
    pinned: str = "",
) -> str:
    """Return the app whose guide is replayed, ``application_id`` when it is alone.

    Args:
        application_id: the role asking, which is skipped as its own peer.
        running: the apps this round deploys.
        invokable: every app that publishes a guide.
        pinned: the app the round was started for, used when it publishes a
            guide and ignored when it does not, because ``APP_ID`` is set on
            every deploy row and not every row deploys a documented role.
    """
    known = set(invokable)
    if pinned in known:
        return pinned
    peers = [app for app in running if app != application_id and app in known]
    return secrets.choice(peers) if peers else application_id


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
            guide_role(
                application_id,
                running_apps(vars_),
                list_invokable_app_ids(),
                os.environ.get(ENV_VAR, "").strip(),
            )
        ]
