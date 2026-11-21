from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.stacks.makefile import reached_from

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

DECLARATION = PROJECT_ROOT / "compose" / "stacks.yml"
CLASSES = ("always-on", "on-demand", "long-lived")


@dataclass(frozen=True)
class Stack:
    """
    Args:
        name: the key it is declared under.
        lifecycle: its class, one of :data:`CLASSES`.
        needs: the stacks it runs against.
        targets: the make targets whose own recipe reaches it.
        stops: the make targets that stop, pause or remove it and start no stack.
        override: the stack its targets start instead when
            ``INFINITO_STACK_NAME`` names one, or empty.
    """

    name: str
    lifecycle: str
    needs: tuple[str, ...]
    targets: tuple[str, ...]
    stops: tuple[str, ...] = field(default=())
    override: str = ""


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
            stops=tuple(str(target) for target in entry.get("stops") or ()),
            override=str(entry.get("override") or ""),
        )
        for name, entry in declared.items()
    }


def unaddressed(path: Path = DECLARATION) -> tuple[str, ...]:
    """
    Args:
        path: the declaration to read.

    Returns:
        The make targets that load a compose helper and address no stack, or
        only report the state of one.
    """
    return tuple(str(target) for target in load_yaml(path).get("unaddressed") or ())


def declared_targets(stacks: Mapping[str, Stack], free: Iterable[str]) -> set[str]:
    """
    Args:
        stacks: the declaration, as :func:`load` returns it.
        free: the targets :func:`unaddressed` returns.

    Returns:
        Every target the declaration names.
    """
    named = {t for stack in stacks.values() for t in (*stack.targets, *stack.stops)}
    return named | set(free)


def problems(stacks: Mapping[str, Stack], targets: set[str]) -> list[str]:
    """
    Args:
        stacks: the declaration, as :func:`load` returns it.
        targets: every target the Makefile defines.

    Returns:
        One line per breach: an unknown class, a need no stack declares, a
        need on itself, an override no other stack declares, or a target the
        Makefile does not define.
    """
    found: list[str] = []
    for stack in stacks.values():
        if stack.lifecycle not in CLASSES:
            found.append(
                f"{stack.name}: class {stack.lifecycle!r} is not one of {CLASSES}"
            )
        if stack.override and (
            stack.override == stack.name or stack.override not in stacks
        ):
            found.append(
                f"{stack.name}: override {stack.override}, which no other stack declares"
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
            for target in (*stack.targets, *stack.stops)
            if target not in targets
        )
        found.extend(
            f"{stack.name}: target {target} both starts and stops it"
            for target in sorted(set(stack.targets) & set(stack.stops))
        )
    return found


def with_needs(names: set[str], stacks: Mapping[str, Stack]) -> list[str]:
    """
    Args:
        names: the stacks to start.
        stacks: the declaration, as :func:`load` returns it.

    Returns:
        ``names`` and every stack they need, each after the stacks it needs.
    """
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
    target: str,
    stacks: Mapping[str, Stack],
    graph: Mapping[str, set[str]],
    *,
    named: bool = False,
) -> list[str]:
    """
    Args:
        target: the make target.
        stacks: the declaration, as :func:`load` returns it.
        graph: the Makefile's calls, as
            :func:`~utils.stacks.makefile.calls` returns them.
        named: resolve for a set ``INFINITO_STACK_NAME``, where a stack with
            an ``override`` gives way to that stack.

    Returns:
        The stacks *target* starts, each after the stacks it needs.

    Raises:
        KeyError: the Makefile defines no *target*.
    """
    if target not in graph:
        raise KeyError(target)
    reached = reached_from(target, graph)
    direct = {
        (stack.override if named and stack.override else stack.name)
        for stack in stacks.values()
        if any(name in reached for name in stack.targets)
    }
    return with_needs(direct, stacks)
