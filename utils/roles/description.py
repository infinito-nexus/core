from __future__ import annotations

MAX_LENGTH = 120

LEADING_VERBS = frozenset(
    {
        "deploys",
        "deploy",
        "installs",
        "install",
        "runs",
        "run",
        "provides",
        "provide",
        "creates",
        "create",
        "sets",
        "set",
        "configures",
        "configure",
        "manages",
        "manage",
        "serves",
        "serve",
        "builds",
        "build",
        "enables",
        "enable",
        "adds",
        "add",
        "generates",
        "generate",
        "bootstraps",
        "bootstrap",
        "tags",
        "tag",
        "marks",
        "mark",
        "refreshes",
        "refresh",
        "retrieves",
        "retrieve",
        "resolves",
        "resolve",
        "hosts",
        "host",
        "syncs",
        "sync",
        "handles",
        "handle",
        "wires",
        "wire",
    }
)


def violations(description: str) -> list[str]:
    """Return how a ``galaxy_info.description`` breaks the description schema.

    Args:
        description: the stripped description text.

    Returns:
        One short problem per broken rule; empty when the text conforms.
    """
    problems = []
    if len(description) > MAX_LENGTH:
        problems.append(f"{len(description)}>{MAX_LENGTH} chars")
    if description.endswith("."):
        problems.append("trailing period")
    first = description.split(maxsplit=1)[0].strip(".,:").lower() if description else ""
    if first in LEADING_VERBS:
        problems.append(f"starts with verb '{first}'")
    return problems
