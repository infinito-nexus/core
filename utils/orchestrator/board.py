"""The orchestrator's OpenProject board client, the stack-free part.

Board writes come from the orchestrator only, under the acting agent's own
bearer token, against the board the deploy names in ``BOARD_URL`` (the local
``web-app-openproject`` unless the inventory points to another one). A new
requirement enters as a ``Proposed`` work package; an agent starts one only
after a human set it to ``Approved`` and assigned it to the role's group
``agent-<role>``. The HTTP transport is injected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

PROPOSED = "Proposed"
APPROVED = "Approved"
GROUP_PREFIX = "agent-"
API = "/api/v3"


def role_group(role: str) -> str:
    """Return the board group a role's work packages are assigned to.

    Args:
        role: the agent role name.
    """
    return f"{GROUP_PREFIX}{role}"


def _title(work_package: dict, link: str) -> str | None:
    return ((work_package.get("_links") or {}).get(link) or {}).get("title")


def startable(work_package: dict, role: str) -> bool:
    """Return whether ``role`` may start ``work_package``: it is ``Approved``
    and assigned to the role's group.

    Args:
        work_package: the work package as the OpenProject API returns it.
        role: the agent role name.
    """
    return _title(work_package, "status") == APPROVED and _title(
        work_package, "assignee"
    ) == role_group(role)


def assigned_role(work_package: dict) -> str | None:
    """Return the agent role whose group the work package is assigned to.

    Args:
        work_package: the work package as the OpenProject API returns it.
    """
    assignee = _title(work_package, "assignee") or ""
    return assignee[len(GROUP_PREFIX) :] if assignee.startswith(GROUP_PREFIX) else None


@dataclass(frozen=True)
class Board:
    """One OpenProject board.

    Args:
        url: the board's origin, from ``BOARD_URL``.
        transport: sends ``(method, url, headers, body)`` and returns the JSON.
    """

    url: str
    transport: Callable[[str, str, dict, dict | None], dict]

    def _call(self, method: str, path: str, bearer: str, body: dict | None) -> dict:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
        }
        return self.transport(
            method, f"{self.url.rstrip('/')}{API}{path}", headers, body
        )

    def _status_href(self, name: str, bearer: str) -> str:
        statuses = self._call("GET", "/statuses", bearer, None)
        for status in (statuses.get("_embedded") or {}).get("elements") or []:
            if status.get("name") == name:
                return status["_links"]["self"]["href"]
        raise LookupError(f"the board has no status {name!r}")

    def create_work_package(
        self, project: str, subject: str, description: str, bearer: str
    ) -> dict:
        """Create a requirement work package with status ``Proposed``.

        Args:
            project: the project identifier.
            subject: the work package subject.
            description: the markdown description (user story, criteria).
            bearer: the acting agent's own token, so the journal names it.
        """
        body = {
            "subject": subject,
            "description": {"format": "markdown", "raw": description},
            "_links": {"status": {"href": self._status_href(PROPOSED, bearer)}},
        }
        return self._call("POST", f"/projects/{project}/work_packages", bearer, body)
