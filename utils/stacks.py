"""Which local stacks a make target starts, from ``compose/stacks.yml``.

The declaration names, per stack, its lifecycle class, the stacks it runs
against and the targets whose own recipe reaches it. A target that only calls
other targets, as a prerequisite, through ``$(MAKE)`` or through
``scripts/make/parallel.sh``, inherits their stacks, so an aggregate such as
``quality-high`` is never declared twice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

DECLARATION = PROJECT_ROOT / "compose" / "stacks.yml"
MAKEFILE = PROJECT_ROOT / "Makefile"
CLASSES = ("always-on", "on-demand", "long-lived")
CALLERS = ("$(MAKE)", "scripts/make/parallel.sh")
TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)(.*)$")
CONTINUED = "\\"
RECIPE = "\t"


@dataclass(frozen=True)
class Stack:
    """
    Args:
        name: the key it is declared under.
        lifecycle: its class, one of :data:`CLASSES`.
        needs: the stacks it runs against.
        targets: the make targets whose own recipe reaches it.
    """

    name: str
    lifecycle: str
    needs: tuple[str, ...]
    targets: tuple[str, ...]


def load(path: Path = DECLARATION) -> dict[str, Stack]:
    """
    Args:
        path: the declaration to read.

    Returns:
        Every declared stack, keyed by name.
    """
    declared = load_yaml(path).get("stacks") or {}
    return {
        str(name): Stack(
            name=str(name),
            lifecycle=str(entry.get("class", "")),
            needs=tuple(str(need) for need in entry.get("needs") or ()),
            targets=tuple(str(target) for target in entry.get("targets") or ()),
        )
        for name, entry in declared.items()
    }


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


def calls(text: str) -> dict[str, set[str]]:
    """
    Args:
        text: a Makefile.

    Returns:
        Every target, mapped to the targets it runs: its prerequisites and
        every target its recipe hands to ``$(MAKE)`` or ``parallel.sh``.
    """
    lines = _logical_lines(text)
    found: dict[str, set[str]] = {}
    recipes: dict[str, list[str]] = {}
    current = ""
    for line in lines:
        match = None if line.startswith(RECIPE) else TARGET.match(line)
        if match:
            current = match.group(1)
            prerequisites = match.group(2).split("|", 1)[0].split()
            found.setdefault(current, set()).update(prerequisites)
            recipes.setdefault(current, [])
        elif line.startswith(RECIPE) and current:
            recipes[current].append(line)
        elif line.strip() and not line.startswith("#"):
            current = ""
    for target, recipe in recipes.items():
        for line in recipe:
            if any(caller in line for caller in CALLERS):
                words = {word.strip("\"'@") for word in line.split()}
                found[target].update(words & set(found))
    return {target: called & set(found) for target, called in found.items()}


def problems(stacks: Mapping[str, Stack], targets: set[str]) -> list[str]:
    """
    Args:
        stacks: the declaration, as :func:`load` returns it.
        targets: every target the Makefile defines.

    Returns:
        One line per breach: an unknown class, a need no stack declares, a
        need on itself, or a target the Makefile does not define.
    """
    found: list[str] = []
    for stack in stacks.values():
        if stack.lifecycle not in CLASSES:
            found.append(
                f"{stack.name}: class {stack.lifecycle!r} is not one of {CLASSES}"
            )
        found.extend(
            f"{stack.name}: needs {need}, which no stack declares"
            for need in stack.needs
            if need not in stacks
        )
        if stack.name in stack.needs:
            found.append(f"{stack.name}: needs itself")
        found.extend(
            f"{stack.name}: target {target} is not in the Makefile"
            for target in stack.targets
            if target not in targets
        )
    return found


def _reached(target: str, graph: Mapping[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    todo = [target]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(graph.get(name, ()))
    return seen


def _with_needs(names: set[str], stacks: Mapping[str, Stack]) -> list[str]:
    ordered: list[str] = []

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in ordered or name in path:
            return
        for need in sorted(stacks[name].needs):
            visit(need, (*path, name))
        ordered.append(name)

    for name in sorted(names):
        visit(name, ())
    return ordered


def resolve(
    target: str, stacks: Mapping[str, Stack], graph: Mapping[str, set[str]]
) -> list[str]:
    """
    Args:
        target: the make target.
        stacks: the declaration, as :func:`load` returns it.
        graph: the Makefile's calls, as :func:`calls` returns them.

    Returns:
        The stacks *target* starts, each after the stacks it needs.

    Raises:
        KeyError: the Makefile defines no *target*.
    """
    if target not in graph:
        raise KeyError(target)
    reached = _reached(target, graph)
    direct = {
        stack.name
        for stack in stacks.values()
        if any(name in reached for name in stack.targets)
    }
    return _with_needs(direct, stacks)


def makefile_calls(path: Path = MAKEFILE) -> dict[str, set[str]]:
    """
    Args:
        path: the Makefile to read.
    """
    return calls(read_text(str(path)))
