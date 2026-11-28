"""Which account an agent acts under.

An agent's account grants form an ordered list. A grant is active only while
its credentials are present (in the inventory or provisioned); an inactive
grant is skipped. The first active grant is the default account, used by every
routine step that needs an account and names none. When a grant goes inactive,
the next active one becomes the default.

A ``repositories`` entry is ``<owner>/<name>`` or
``<provider>/<label>:<owner>/<name>``; one that names an account is worked
through that account instead of the default, and a repository the list does
not name is refused.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_SEGMENT = r"(?!\.+(?:/|\Z))[A-Za-z0-9_.-]+"
_SLUG = re.compile(rf"{_SEGMENT}/{_SEGMENT}")


def available_accounts(
    credentials: Mapping[str, object], provisioned: Iterable[str]
) -> set[str]:
    """Return the account grants whose credentials are present.

    Args:
        credentials: the agent's ``credentials`` with the inventory's
            ``agents.<role>.credentials`` folded on top, keyed by the grant
            ``<provider>/<label>``; an empty entry counts as absent.
        provisioned: the grants the provisioner holds a record for.
    """
    present = {grant for grant, entry in (credentials or {}).items() if entry}
    return present | set(provisioned)


def active_accounts(ordered_grants: list[str], available: set[str]) -> list[str]:
    """Return the grants whose credentials are present, in order.

    Args:
        ordered_grants: the agent's account grants, highest priority first.
        available: the grants whose credentials are present.
    """
    return [grant for grant in ordered_grants if grant in available]


def default_account(ordered_grants: list[str], available: set[str]) -> str | None:
    """Return the agent's default account: the first active grant, or None when
    no grant has its credentials."""
    active = active_accounts(ordered_grants, available)
    return active[0] if active else None


def repository_entry(entry: str) -> dict[str, str | None]:
    """Return one ``repositories`` entry as ``{"repo", "account"}``, the
    account ``None`` when the entry names none.

    Args:
        entry: ``<owner>/<name>`` or ``<provider>/<label>:<owner>/<name>``.

    Raises:
        ValueError: the entry has neither shape, or a segment is all dots.
    """
    account, _, repo = str(entry).rpartition(":")
    if not _SLUG.fullmatch(repo) or (account and not _SLUG.fullmatch(account)):
        raise ValueError(
            f"repositories entry {entry!r}: expected "
            "[<provider>/<label>:]<owner>/<name>"
        )
    return {"repo": repo, "account": account or None}


def repository_accounts(
    repositories: list[str], ordered_grants: list[str], available: set[str]
) -> list[dict[str, str | None]]:
    """Return every listed repository with the account it is worked through:
    the account its entry names, else the default account. A named account
    without credentials leaves the repository without an account; it never
    falls back to the default.

    Args:
        repositories: the agent's ``repositories`` entries.
        ordered_grants: the agent's account grants, highest priority first.
        available: the grants whose credentials are present.

    Raises:
        ValueError: an entry is malformed or names an account the agent has
            no grant for.
    """
    default = default_account(ordered_grants, available)
    scope: list[dict[str, str | None]] = []
    for raw in repositories:
        entry = repository_entry(raw)
        named = entry["account"]
        if named is None:
            scope.append({"repo": entry["repo"], "account": default})
            continue
        if named not in ordered_grants:
            raise ValueError(f"repositories entry {raw!r}: no account grant {named!r}")
        scope.append(
            {"repo": entry["repo"], "account": named if named in available else None}
        )
    return scope


def worked_through(scope: list[dict[str, str | None]], repo: str) -> str:
    """Return the account ``repo`` is worked through.

    Args:
        scope: the result of ``repository_accounts``.
        repo: the ``<owner>/<name>`` a step works on.

    Raises:
        PermissionError: ``repo`` is not in the agent's ``repositories``, or
            its account has no credentials.
    """
    for entry in scope:
        if entry["repo"] != repo:
            continue
        if entry["account"] is None:
            raise PermissionError(f"{repo}: its account has no credentials")
        return str(entry["account"])
    raise PermissionError(f"{repo}: not in the agent's repositories")


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    grants = ["github/maintainer", "gitea/maintainer", "gitlab/maintainer"]
    _expect(
        default_account(grants, {"github/maintainer", "gitea/maintainer"})
        == "github/maintainer",
        "first active grant not default",
    )
    _expect(
        default_account(grants, {"gitea/maintainer", "gitlab/maintainer"})
        == "gitea/maintainer",
        "next active grant not promoted when creds gone",
    )
    _expect(default_account(grants, set()) is None, "default with no creds is not None")
    _expect(
        active_accounts(grants, {"gitlab/maintainer"}) == ["gitlab/maintainer"],
        "active grants not filtered to available",
    )
    _expect(
        default_account(grants, {"gitlab/maintainer", "github/maintainer"})
        == "github/maintainer",
        "grant order must decide, not cred order",
    )
    print("account selection self-check ok")


if __name__ == "__main__":
    _demo()
