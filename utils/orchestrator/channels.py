"""Channel addressing and the channel contract for the orchestrator.

A message is addressed to an agent account or a human username, never to a
session name: a session comes and goes, but the account is the stable
identity a reply must reach. This rejects a recipient that looks like a
session id so a message is never bound to a transient session.

The channel contract turns one message into the request a channel's
transport sends. Matrix is the first implementation, email through
``sys-svc-mail`` the second, Zammad the third; each takes the same
``envelope(recipient, text)`` call and refuses a recipient that is not
addressable, so the orchestrator talks to every channel the same way. The
transport itself is I/O the deployed orchestrator performs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from utils.agents.naming import is_agent_name, is_human_name

_SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def is_addressable(recipient: str) -> bool:
    """Return whether ``recipient`` is an account a message may target: an
    agent account or a human username, and not a session id."""
    if _SESSION_ID.match(recipient):
        return False
    return is_agent_name(recipient) or is_human_name(recipient)


def _addressable(recipient: str) -> str:
    if not is_addressable(recipient):
        raise ValueError(f"{recipient!r} is not an agent account or human username")
    return recipient


class Channel(Protocol):
    """The channel contract: ``name``, the remote live instance it reaches
    (``""`` for the local one), the handle of its login credential (``""``
    for none) and the request for one message."""

    name: str
    remote: str
    credential: str

    def envelope(self, recipient: str, text: str) -> dict:
        """Return the request that delivers ``text`` to ``recipient``.

        Args:
            recipient: an agent account or human username.
            text: the message body.

        Raises:
            ValueError: ``recipient`` is not addressable.
        """


@dataclass(frozen=True)
class MatrixChannel:
    """A direct message on the platform's Matrix homeserver.

    Args:
        homeserver: the server name of the homeserver.
        remote: the remote live instance the homeserver belongs to, or ``""``.
        credential: the handle of the adapter's login credential, or ``""``.
    """

    homeserver: str
    remote: str = ""
    credential: str = ""
    name: str = "matrix"

    def envelope(self, recipient: str, text: str) -> dict:
        return {
            "channel": self.name,
            "to": f"@{_addressable(recipient)}:{self.homeserver}",
            "content": {"msgtype": "m.text", "body": text},
        }


@dataclass(frozen=True)
class EmailChannel:
    """A mail through ``sys-svc-mail`` to the account's platform mailbox.

    Args:
        domain: the mail domain of the platform's accounts.
        sender: the orchestrator's own sender address.
        remote: the remote live instance the mail domain belongs to, or ``""``.
        credential: the handle of the submission credential, or ``""``.
    """

    domain: str
    sender: str
    remote: str = ""
    credential: str = ""
    name: str = "email"

    def envelope(self, recipient: str, text: str) -> dict:
        subject = text.splitlines()[0] if text else ""
        return {
            "channel": self.name,
            "to": f"{_addressable(recipient)}@{self.domain}",
            "from": self.sender,
            "subject": subject,
            "body": text,
        }


@dataclass(frozen=True)
class ZammadChannel:
    """An internal note on a Zammad ticket for the account.

    Args:
        group: the Zammad group the ticket belongs to.
        remote: the remote live instance the Zammad belongs to, or ``""``.
        credential: the handle of the API credential, or ``""``.
    """

    group: str
    remote: str = ""
    credential: str = ""
    name: str = "zammad"

    def envelope(self, recipient: str, text: str) -> dict:
        return {
            "channel": self.name,
            "to": _addressable(recipient),
            "ticket": {
                "group": self.group,
                "customer": recipient,
                "article": {"body": text, "type": "note", "internal": True},
            },
        }


def dispatch(channels: list[Channel], recipient: str, text: str) -> dict:
    """Return the request of the channel that carries the message: the first
    remote-instance channel holding a credential, else the first local one,
    in priority order. A remote channel without a credential carries nothing.

    Args:
        channels: the enabled channels, highest priority first.
        recipient: an agent account or human username.
        text: the message body.

    Raises:
        ValueError: no channel is usable or ``recipient`` is not addressable.
    """
    remote = [channel for channel in channels if channel.remote and channel.credential]
    local = [channel for channel in channels if not channel.remote]
    usable = remote or local
    if not usable:
        raise ValueError("no channel configured")
    return usable[0].envelope(recipient, text)


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    _expect(is_addressable("mant0alice"), "agent account not addressable")
    _expect(is_addressable("biber"), "human not addressable")
    _expect(
        not is_addressable("ffb7d068-2d34-44a4-b22a-95cc880a6dc8"),
        "session id addressable",
    )
    _expect(not is_addressable("agent-hermes-9f1e"), "session-style name addressable")
    print("orchestrator channels self-check ok")


if __name__ == "__main__":
    _demo()
