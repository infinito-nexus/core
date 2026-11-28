from __future__ import annotations

from typing import Any

GO_TEMPLATE_OPEN = "{{"
GO_TEMPLATE_OPEN_LITERAL = '{{"{{"}}'


def swarm_env_literal(value: Any) -> str:
    """Args:
        value: an env value a swarm service receives, which swarmkit expands
            as a Go template before the container starts.

    Returns:
        The value with every ``{{`` written as the Go template action that
        prints it, so the expansion hands the container the value unchanged.
    """
    text = "" if value is None else str(value)
    return text.replace(GO_TEMPLATE_OPEN, GO_TEMPLATE_OPEN_LITERAL)


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "swarm_env_literal": swarm_env_literal,
        }
