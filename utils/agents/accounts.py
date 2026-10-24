"""Which account an agent acts under.

An agent's account grants form an ordered list. A grant is active only while
its credentials are present (in the inventory or provisioned); an inactive
grant is skipped. The first active grant is the default account, used by every
routine step that needs an account and names none. When a grant goes inactive,
the next active one becomes the default.
"""

from __future__ import annotations


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
