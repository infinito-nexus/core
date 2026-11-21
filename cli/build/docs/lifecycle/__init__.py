from __future__ import annotations

from typing import TYPE_CHECKING

from cli.build.docs import markers

if TYPE_CHECKING:
    from utils.roles.lifecycle import Lifecycle

DOC = "docs/contributing/design/role/services/lifecycle.md"
BEGIN = "<!-- lifecycle-diagram:begin -->"
END = "<!-- lifecycle-diagram:end -->"
LEGEND = (
    "Solid arrows are the moves a role may make between statuses; dotted arrows "
    "lead from a CI trigger context to every status its test-deploy discovery "
    "picks by default. Rendered from `meta/lifecycle.yml` by the docs build."
)


def _id(prefix: str, name: str) -> str:
    return prefix + "".join(char if char.isalnum() else "_" for char in name)


def render(spot: Lifecycle) -> str:
    """The managed block: the legend and the Mermaid flowchart.

    Args:
        spot: the loaded ``meta/lifecycle.yml``.
    """
    lines = [LEGEND, "", "```mermaid", "flowchart LR"]
    for name in spot.order:
        flags = ", ".join(sorted(spot.statuses[name].flags))
        label = f"{name}<br>{flags}" if flags else name
        lines.append(f'    {_id("s_", name)}["{label}"]')
    for name in spot.order:
        predecessors = frozenset(spot.statuses[name].predecessors)
        lines.extend(
            f"    {_id('s_', pred)} --> {_id('s_', name)}"
            for pred in spot.ordered(predecessors)
        )
    for context in spot.contexts.values():
        node = _id("c_", context.name)
        lines.append(f'    {node}{{{{"CI {context.name}"}}}}')
        lines.extend(
            f"    {node} -.-> {_id('s_', name)}"
            for name in spot.ordered(spot.deployed_in(context.name))
        )
    lines.append("```")
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    """*text* with everything between the lifecycle markers replaced by *block*.

    Args:
        text: the document.
        block: the rendered block.

    Raises:
        ValueError: the markers are missing, repeated or out of order.
    """
    return markers.replace_block(text, block, begin=BEGIN, end=END, doc=DOC)
