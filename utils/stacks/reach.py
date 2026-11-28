from __future__ import annotations

from typing import TYPE_CHECKING

from utils.stacks.makefile import make_calls, parse, reached_from

if TYPE_CHECKING:
    from utils.stacks.sources import SourceGraph

HELPERS = frozenset(
    {
        "scripts/meta/compose.sh",
        "cli/administration/deploy/development/stack.py",
    }
)


def reaching(
    makefile: str, graph: SourceGraph, sinks: frozenset[str] = HELPERS
) -> dict[str, list[str]]:
    """
    Args:
        makefile: the Makefile text.
        graph: the source files the recipes run.
        sinks: the files to reach, the compose helpers by default.

    Returns:
        Every target whose own recipe reaches one of ``sinks``, mapped to one
        chain of files and ``make <target>`` steps from the recipe to it; the
        targets a recipe hands to ``$(MAKE)`` or ``parallel.sh`` are left to
        :func:`~utils.stacks.makefile.calls`, while a bare ``make`` call is
        followed.
    """
    targets, bodies = parse(makefile)

    def recipe_files(name: str) -> set[str]:
        return {
            path
            for line in bodies.get(name, ())
            for path in graph.line_files("Makefile", line)
        }

    found: dict[str, list[str]] = {}
    for target in sorted(bodies):
        scripted = {
            f"make {called}"
            for line in bodies[target]
            for called in make_calls(line)
            if called in targets
        }
        parent: dict[str, str] = dict.fromkeys(
            sorted(recipe_files(target) | scripted), ""
        )
        todo = list(parent)
        while todo:
            node = todo.pop(0)
            if node in sinks:
                chain = [node]
                while parent[chain[-1]]:
                    chain.append(parent[chain[-1]])
                found[target] = chain[::-1]
                break
            if node.startswith("make "):
                nexts = {
                    path
                    for called in sorted(reached_from(node[len("make ") :], targets))
                    for path in recipe_files(called)
                }
            else:
                files, scripted = graph.edges(node)
                nexts = set(files) | {f"make {t}" for t in scripted if t in targets}
            for step in sorted(nexts - parent.keys()):
                parent[step] = node
                todo.append(step)
    return found
