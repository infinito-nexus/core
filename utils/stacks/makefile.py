from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

MAKEFILE = PROJECT_ROOT / "Makefile"
CALLERS = ("$(MAKE)", "scripts/make/parallel.sh")
TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)(.*)$")
CONTINUED = "\\"
RECIPE = "\t"
MAKE_REF = re.compile(
    r"""(?:(?<![\w$"'/.-])make|"\$\{MAKE(?::-make)?\}")"""
    r"""(?:\s+-C\s+\S+)?(?:\s+--?[\w-]+)*\s+([a-z][\w-]*)"""
)


def _logical_lines(text: str) -> list[str]:
    joined: list[str] = []
    pending = ""
    for line in text.splitlines():
        if line.endswith(CONTINUED):
            pending += line[:-1] + " "
            continue
        joined.append(pending + line)
        pending = ""
    return joined


def recipes(text: str) -> dict[str, list[str]]:
    """
    Args:
        text: a Makefile.

    Returns:
        Every target, mapped to its recipe lines, continuations joined.
    """
    return parse(text)[1]


def calls(text: str) -> dict[str, set[str]]:
    """
    Args:
        text: a Makefile.

    Returns:
        Every target, mapped to the targets it runs: its prerequisites and
        every target its recipe hands to ``$(MAKE)`` or ``parallel.sh``.
    """
    return parse(text)[0]


def parse(text: str) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """
    Args:
        text: a Makefile.

    Returns:
        :func:`calls` and :func:`recipes` of the Makefile, read in one pass.
    """
    lines = _logical_lines(text)
    found: dict[str, set[str]] = {}
    bodies: dict[str, list[str]] = {}
    current = ""
    for line in lines:
        match = None if line.startswith(RECIPE) else TARGET.match(line)
        if match:
            current = match.group(1)
            prerequisites = match.group(2).split("|", 1)[0].split()
            found.setdefault(current, set()).update(prerequisites)
            bodies.setdefault(current, [])
        elif line.startswith(RECIPE) and current:
            bodies[current].append(line)
        elif line.strip() and not line.startswith("#"):
            current = ""
    for target, recipe in bodies.items():
        for line in recipe:
            if any(caller in line for caller in CALLERS):
                words = {word.strip("\"'@") for word in line.split()}
                found[target].update(words & set(found))
    graph = {target: called & set(found) for target, called in found.items()}
    return graph, bodies


def reached_from(target: str, graph: Mapping[str, set[str]]) -> set[str]:
    """
    Args:
        target: the make target.
        graph: the Makefile's calls, as :func:`calls` returns them.

    Returns:
        The target itself and every target it runs, directly or through others.
    """
    seen: set[str] = set()
    todo = [target]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(graph.get(name, ()))
    return seen


def makefile_calls(path: Path = MAKEFILE) -> dict[str, set[str]]:
    """
    Args:
        path: the Makefile to read.
    """
    return calls(read_text(str(path)))


def _quoted(line: str, position: int) -> bool:
    prefix = line[:position]
    return prefix.count('"') % 2 == 1 or prefix.count("'") % 2 == 1


def make_calls(line: str) -> set[str]:
    """
    Args:
        line: one shell line.

    Returns:
        The targets the line runs through ``make`` or ``${MAKE:-make}``,
        outside quoted text.
    """
    return {
        match.group(1)
        for match in MAKE_REF.finditer(line)
        if not _quoted(line, match.start())
    }


def closure(direct: Iterable[str], graph: Mapping[str, set[str]]) -> set[str]:
    """
    Args:
        direct: the targets whose own recipe reaches something.
        graph: the Makefile's calls, as :func:`calls` returns them.

    Returns:
        Every target that runs one of ``direct``, itself, as a prerequisite or
        through ``$(MAKE)`` or ``parallel.sh``.
    """
    hits = set(direct)
    return {target for target in graph if reached_from(target, graph) & hits}
