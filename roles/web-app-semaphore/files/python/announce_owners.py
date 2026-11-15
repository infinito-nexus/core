from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from export_task import (
    DAY_MS,
    FAILURES,
    KEYCLOAK_ENV,
    LOGIN_ENV,
    MAIL_ENV,
    OWNERS_PATH,
    PLATFORM_MOUNT,
    UUID,
    ExportRefusedError,
    ExportTask,
    bao_client,
    iso,
    membership_path,
    now_ms,
    reason,
    recent_join,
    task_opener,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from export_task import Opener

    from utils.openbao_client import OpenBaoClient

ROLE = "announce-owners"
REQUIRED_ENV = (*LOGIN_ENV, *KEYCLOAK_ENV, *MAIL_ENV, "EXPORT_OWNER_MIN_AGE_DAYS")


class Announcer(ExportTask):
    def __init__(
        self, environ: Mapping[str, str], opener: Opener, bao: OpenBaoClient
    ) -> None:
        """
        Args:
            environ: the task environment; see ``REQUIRED_ENV``.
            opener: see ``ExportTask``.
            bao: see ``ExportTask``.
        """
        super().__init__(environ, REQUIRED_ENV, opener, bao)
        self.min_age_days = int(environ["EXPORT_OWNER_MIN_AGE_DAYS"])

    def records(self) -> list[str]:
        """
        Returns:
            The name of every pinned ``Owner`` group record, ``ws-<id>``.
        """
        return sorted(self.bao.list_tree(PLATFORM_MOUNT, OWNERS_PATH))

    def pinned_group(self, record: str) -> tuple[str, str]:
        """
        Args:
            record: one of ``records``.

        Returns:
            The workspace id and the id of its pinned ``Owner`` group.
        """
        workspace = record.removeprefix("ws-")
        if record == workspace or not UUID.fullmatch(workspace):
            raise ExportRefusedError("the record names no workspace")
        group = self.bao.read_all(PLATFORM_MOUNT, OWNERS_PATH + record).get("group")
        if not group:
            raise ExportRefusedError("the record holds no group")
        return workspace, str(group)

    def announce(self, record: str, now: int) -> list[str]:
        """
        Args:
            record: one of ``records``.
            now: the current time in epoch milliseconds.

        Returns:
            One line per Owner the run announced, each mailed to every direct
            member of the pinned group.
        """
        workspace, group = self.pinned_group(record)
        organization = self.organization(workspace)
        members = self.members(organization, group)
        announced = []
        for member in members:
            path = membership_path(organization, group, str(member["id"]))
            joined = recent_join(
                self.membership_events(path), path, now, self.min_age_days
            )
            if joined is None:
                continue
            self.mail(
                members,
                f"New Owner of workspace ws-{workspace}",
                notice(workspace, member, joined, self.min_age_days),
            )
            announced.append(f"{record}: announced {member['id']}")
        return announced


def notice(
    workspace: str, member: Mapping[str, Any], joined: int, min_age_days: int
) -> str:
    """
    Args:
        workspace: the workspace id.
        member: the Keycloak user who joined the pinned group.
        joined: the time of the join in epoch milliseconds.
        min_age_days: ``owner_min_age_days``.

    Returns:
        The text that names the new Owner, the join and the first export day.
    """
    return (
        f"Workspace: ws-{workspace}\n"
        f"New Owner: {member.get('username', '')} <{member.get('email', '')}> ({member['id']})\n"
        f"Joined: {iso(joined)}\n"
        f"First export possible: {iso(joined + min_age_days * DAY_MS)}\n"
        "Remove the account from the Owner group before then if you do not know it.\n"
    )


def run(
    environ: Mapping[str, str], opener: Opener, now: int
) -> tuple[list[str], list[str]]:
    """
    Args:
        environ: see ``Announcer``.
        opener: see ``Announcer``.
        now: the current time in epoch milliseconds.

    Returns:
        The lines of every announcement and of every workspace whose
        announcement failed; one failure never stops the others.
    """
    announcer = Announcer(environ, opener, bao_client(environ))
    announcer.login(ROLE)
    announcer.keycloak_login()
    announced, failures = [], []
    for record in announcer.records():
        try:
            announced.extend(announcer.announce(record, now))
        except FAILURES as exc:
            failures.append(f"{record}: {reason(exc)}")
    return announced, failures


def main(argv: list[str]) -> int:
    if argv:
        print(f"announce owners: takes no argument, got {argv[0]!r}", file=sys.stderr)
        return 2
    try:
        announced, failures = run(os.environ, task_opener(os.environ), now_ms())
    except FAILURES as exc:
        print(f"announce owners refused: {reason(exc)}", file=sys.stderr)
        return 1
    for line in announced:
        print(line)
    for line in failures:
        print(f"announce owners failed: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
