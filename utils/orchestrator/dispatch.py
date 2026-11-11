"""Which agent role a trigger starts, through which gate, and who hears of it.

A trigger reaches every role whose ``agent.yml`` lists it, with the security
controls on top: an outsider's event (an issue from a non-collaborator, a
fork pull request run) only ever starts the planner, and a gated role on a
trigger outside its exemptions goes through the planner and the ``Approved``
gate instead of starting itself. The maintainer is exempt only on failed runs
of the own repository's CI and on security alerts. A board work package
starts the role whose group it is assigned to, only once it is ``Approved``.
A failed run and a new pull request also notify the owner of every role the
trigger reached, through the channel contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.orchestrator.board import assigned_role, startable
from utils.orchestrator.load import START

if TYPE_CHECKING:
    from utils.orchestrator.webhook import Event

PLANNER = "planner"
GATED = {
    "maintainer": frozenset({"workflow_run_failed", "security_alert"}),
    "implementer": frozenset(),
}
NOTICES = {
    "workflow_run_failed": "A CI run of {repository} failed.",
    "pull_request_opened": "A new pull request was opened on {repository}.",
}


def route(event: Event, triggers: dict[str, list[str]]) -> list[str]:
    """Return the roles ``event`` starts.

    Args:
        event: the trigger read from the re-fetched object.
        triggers: the triggers each role's ``agent.yml`` lists, by role.
    """
    roles = set()
    for role, listed in triggers.items():
        if event.trigger not in listed:
            continue
        exempt = GATED.get(role)
        if event.outsider or (exempt is not None and event.trigger not in exempt):
            roles.add(PLANNER)
        else:
            roles.add(role)
    return sorted(roles)


def routine_of(role: str, entries: list[dict], routines: list[str]) -> str | None:
    """Return the routine ``role`` runs: the one its cron entries start, else
    the routine named like the role, else ``None``.

    Args:
        role: the agent role name.
        entries: the deployed cron entries, each tagged with its ``role``.
        routines: the routines of the deployed revision.
    """
    for entry in entries:
        if entry.get("role") == role and entry.get("action") == START:
            return entry["routine"]
    return role if role in routines else None


def board_start(work_package: dict, triggers: dict[str, list[str]]) -> str | None:
    """Return the role an assigned work package starts, or ``None`` while it
    is not ``Approved`` or its role takes no board assignment.

    Args:
        work_package: the work package as the board's API returns it.
        triggers: the triggers each role's ``agent.yml`` lists, by role.
    """
    role = assigned_role(work_package)
    if role is None or "board_assignment" not in triggers.get(role, []):
        return None
    return role if startable(work_package, role) else None


def notices(
    event: Event, roles: list[str], owners: dict[str, str]
) -> list[tuple[str, str]]:
    """Return ``(owner, text)`` for every owner of a reached role on a failed
    run or a new pull request; nothing for any other trigger.

    Args:
        event: the trigger read from the re-fetched object.
        roles: the roles ``route`` returned.
        owners: the owner each role's ``agent.yml`` names, by role.
    """
    template = NOTICES.get(event.trigger)
    if template is None:
        return []
    text = template.format(repository=event.repository)
    return [
        (owner, text) for owner in sorted({owners[r] for r in roles if r in owners})
    ]
