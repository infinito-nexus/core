"""How an agent's credentials are released from its KeePass database.

Each agent keeps all its credentials in its own `.kdbx`, the single source.
``keepass.mode`` decides who opens it:

- ``broker`` (default): the broker holds the master key, opens the database and
  releases single entries through the credential helper, the ssh-agent socket
  and token minting. No long-lived credential is stored inside the workspace.
- ``agent``: the agent holds the master key itself and works fully
  autonomously; this is an explicit release set per role in the inventory.

This returns the release policy for a mode; the broker and the deploy enforce
it.
"""

from __future__ import annotations

MODES = ("broker", "agent")


def release_policy(mode: str) -> dict:
    """Return the credential-release policy for ``mode``.

    Keys: ``holder`` (who holds the master key), ``per_entry_release`` (whether
    credentials are handed out one entry at a time), ``workspace_holds_master``
    (whether the master key sits in the agent workspace).

    Raises:
        ValueError: if ``mode`` is not broker or agent.
    """
    if mode not in MODES:
        raise ValueError(f"keepass.mode {mode!r} is not broker or agent")
    if mode == "broker":
        return {
            "holder": "broker",
            "per_entry_release": True,
            "workspace_holds_master": False,
        }
    return {
        "holder": "agent",
        "per_entry_release": False,
        "workspace_holds_master": True,
    }


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    broker = release_policy("broker")
    _expect(broker["holder"] == "broker", "broker holder not broker")
    _expect(broker["per_entry_release"] is True, "broker per-entry release not set")
    _expect(
        broker["workspace_holds_master"] is False, "broker mode leaks the master key"
    )
    agent = release_policy("agent")
    _expect(
        agent["holder"] == "agent" and agent["workspace_holds_master"] is True,
        "agent mode policy wrong",
    )
    for bad in ("", "Broker", "root", None):
        try:
            release_policy(bad)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"accepted bad mode {bad!r}")
    print("keepass policy self-check ok")


if __name__ == "__main__":
    _demo()
