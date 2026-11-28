from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.stacks.declaration import Stack, with_needs
from utils.stacks.makefile import calls, closure, make_calls
from utils.stacks.reach import reaching
from utils.stacks.sites import start_sites

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from utils.stacks.sources import SourceGraph

NAMED_GUARD = re.compile(
    r'^(\s*)if \[\[ -z "\$\{INFINITO_STACK_NAME:-\}" \]\]; then\s*$'
)
GUARD_EXIT = re.compile(r"^\s*exit(?:\s+(?:\d+|\$\?))?\s*$")
CONTINUES = re.compile(r"(?:\\|&&|\|[|&]?)\s*(?:#.*)?$")
HEREDOC = "<<"
ARM_END = ";;"
BLOCK_CLOSE = re.compile(r"^\s*(?:(?:fi|done|esac)\b|[)}])")
NAMED_START = "compose-up"


def without_named_start(text: str) -> str:
    """
    Args:
        text: a shell script.

    Returns:
        The script without its ``make`` :data:`NAMED_START` calls that run
        only for a set ``INFINITO_STACK_NAME``: those after an
        ``if [[ -z "${INFINITO_STACK_NAME:-}" ]]`` block whose last top-level
        statement is an unconditional ``exit``, up to the end of that ``case``
        arm or the first line that closes an enclosing block.
    """
    lines = text.splitlines()
    kept = list(lines)
    for index, line in enumerate(lines):
        guard = NAMED_GUARD.match(line)
        if not guard:
            continue
        indent = guard.group(1)
        end = next(
            (at for at in range(index + 1, len(lines)) if lines[at] == f"{indent}fi"),
            None,
        )
        if end is None or not _exits(lines[index + 1 : end], indent):
            continue
        for at in range(end + 1, len(lines)):
            current = lines[at]
            if (
                current.strip() == ARM_END
                or BLOCK_CLOSE.match(current)
                or (current.strip() and not current.startswith(indent))
            ):
                break
            if make_calls(current) == {NAMED_START}:
                kept[at] = ""
    return "\n".join(kept) + "\n"


def _exits(block: list[str], indent: str) -> bool:
    body = [
        line for line in block if line.strip() and not line.lstrip().startswith("#")
    ]
    if not body:
        return False
    inner = body[0][: len(body[0]) - len(body[0].lstrip())]
    return (
        len(inner) > len(indent)
        and inner.startswith(indent)
        and all(line.startswith(inner) for line in body)
        and body[-1][len(inner) :] == body[-1].lstrip()
        and bool(GUARD_EXIT.match(body[-1]))
        and not (len(body) > 1 and CONTINUES.search(body[-2]))
        and not any(HEREDOC in line for line in body)
    )


def starters(
    makefile: str, graph: SourceGraph, stacks: Mapping[str, Stack]
) -> dict[str, dict[str, list[str]]]:
    """
    Args:
        makefile: the Makefile text.
        graph: the source files the recipes run.
        stacks: the declaration, as :func:`~utils.stacks.declaration.load`
            returns it.

    Returns:
        Per stack of :func:`~utils.stacks.sites.start_sites`, every target
        whose own recipe starts it, mapped to one chain; in the start sites of
        a stack whose ``override`` names it, the named-stack start of
        :func:`without_named_start` is no edge.
    """
    sites = start_sites(graph)
    found: dict[str, dict[str, list[str]]] = {}
    for name, sinks in sites.items():
        named = {
            site: without_named_start(graph.text(site))
            for other in stacks.values()
            if other.override == name
            for site in sites.get(other.name, ())
        }
        found[name] = reaching(makefile, graph.rewritten(named), sinks)
    return found


def start_problems(
    makefile: str,
    graph: SourceGraph,
    stacks: Mapping[str, Stack],
    free: Iterable[str],
) -> list[str]:
    """
    Args:
        makefile: the Makefile text.
        graph: the source files the recipes run.
        stacks: the declaration, as :func:`~utils.stacks.declaration.load`
            returns it.
        free: the targets :func:`~utils.stacks.declaration.unaddressed`
            returns.

    Returns:
        One line per target that starts a stack of
        :func:`~utils.stacks.sites.start_sites` outside the `targets` of that
        stack, and per target under `stops` of any stack or `unaddressed` that
        starts any stack of :func:`~utils.stacks.sites.start_sites`, and with
        it the stacks it needs, through any chain of prerequisites,
        ``$(MAKE)`` or scripts.
    """
    targets = calls(makefile)
    found = [
        f"{target} starts {name} outside its targets: {' -> '.join(chain)}"
        for name, chains in starters(makefile, graph, stacks).items()
        for target, chain in sorted(chains.items())
        if target not in stacks[name].targets
    ]
    exempt = {target for stack in stacks.values() for target in stack.stops}
    exempt |= set(free)
    for name, sinks in start_sites(graph).items():
        started = ", ".join(with_needs({name}, stacks))
        found.extend(
            f"{target} stops or addresses no stack, yet starts {started}"
            for target in sorted(closure(reaching(makefile, graph, sinks), targets))
            if target in exempt
        )
    return found
