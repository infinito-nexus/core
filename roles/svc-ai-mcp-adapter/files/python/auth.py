from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

DENY_UNAUTHENTICATED = "unauthenticated"


def authorize_client(expected: str, presented: str) -> None:
    """Refuse a caller that did not present the adapter's own bearer.

    Args:
        expected: the bearer this instance was issued.
        presented: the ``Authorization`` header value the caller sent.

    The upstream credential authenticates the adapter *to* the provider. It
    says nothing about who called the adapter, which is exactly the gap the
    project-owned MCP sidecars leave open.
    """
    prefix = "Bearer "
    token = presented[len(prefix) :] if presented.startswith(prefix) else ""
    if (
        not expected
        or not token
        or not hmac.compare_digest(token.encode(), expected.encode())
    ):
        raise PermissionError(DENY_UNAUTHENTICATED)


def authorize_agent(tokens: Mapping[str, str], agent: str, presented: str) -> None:
    """Refuse a caller whose bearer is not the token of the agent it names.

    Args:
        tokens: agent account name to the token issued to that agent.
        agent: the agent the caller names in ``X-Infinito-Agent``.
        presented: the ``Authorization`` header value the caller sent.

    The bearer is compared against the named agent's token only, in constant
    time, so one agent's token never authenticates another agent.
    """
    authorize_client(tokens.get(agent, ""), presented)
