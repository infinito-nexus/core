from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from utils.stacks.sources import SourceGraph

REMOVAL = "down"
START = "up"
DEPLOY = "deploy"
TEST_RUNNER = "test-runner"
RUNNER_START = re.compile(r"(?m)^[^#\n]*\binfinito_test_runner_exec\s+[^\s(]")
VOLUME_REMOVAL = re.compile(
    r"(?m)^[^#\n]*\binfinito_compose\s+rm\b[^#\n]*\s(?:-v|--volumes)\b"
)
VOLUME_FLAGS = frozenset({"-v", "--volumes"})
RM_WORD = re.compile(r"""["']rm["']""")


def _calls_verb(node: ast.AST, verb: str) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr == verb and not node.args:
        return True
    first = node.args[0] if node.args else None
    return (
        node.func.attr == "run"
        and isinstance(first, ast.List)
        and bool(first.elts)
        and isinstance(first.elts[0], ast.Constant)
        and first.elts[0].value == verb
    )


def _verb_outside_primitive(tree: ast.AST, verb: str) -> bool:
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.FunctionDef) and node.name == verb:
            continue
        if _calls_verb(node, verb):
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


def stack_calls(graph: SourceGraph, verb: str) -> frozenset[str]:
    """
    Args:
        graph: the source files to search.
        verb: the compose verb, :data:`REMOVAL` or :data:`START`.

    Returns:
        Every file that runs ``verb`` on the checkout's stack through the
        compose helper: an ``infinito_compose <verb>`` line, or a Python
        ``.<verb>()`` or ``.run(["<verb>", ...])`` call outside the method
        named ``verb`` that implements it.
    """
    shell = re.compile(rf"(?m)^[^#\n]*\binfinito_compose\s+{verb}\b")
    found: set[str] = set()
    for rel in graph.files:
        text = graph.text(rel)
        if rel.endswith(".sh"):
            if shell.search(text):
                found.add(rel)
            continue
        if f'"{verb}"' not in text and f".{verb}(" not in text:
            continue
        tree = graph.tree(rel)
        if tree is not None and _verb_outside_primitive(tree, verb):
            found.add(rel)
    return frozenset(found)


def _drops_volumes(call: ast.AST) -> bool:
    if not (isinstance(call, ast.Call) and call.args):
        return False
    node = call.args[0]
    if not (isinstance(node, (ast.List, ast.Tuple)) and node.elts):
        return False
    words = [
        element.value if isinstance(element, ast.Constant) else None
        for element in node.elts
    ]
    return words[:3] == ["docker", "volume", "rm"] or (
        words[0] == "rm" and bool(VOLUME_FLAGS & set(words))
    )


def volume_removals(graph: SourceGraph) -> frozenset[str]:
    """
    Args:
        graph: the source files to search.

    Returns:
        Every file that removes services of the checkout's stack with their
        volumes without taking the whole stack down: an
        ``infinito_compose rm -v`` line, or a Python call whose first argument
        is a literal list or tuple that runs ``rm`` with ``-v``/``--volumes``
        or ``docker volume rm``; an argv built at runtime is not seen. A shell
        ``docker volume rm`` names a swarm lab or drill volume, never one of
        the checkout's stack, so it is left out.
    """
    found: set[str] = set()
    for rel in graph.files:
        text = graph.text(rel)
        if rel.endswith(".sh"):
            if VOLUME_REMOVAL.search(text):
                found.add(rel)
            continue
        if not RM_WORD.search(text):
            continue
        tree = graph.tree(rel)
        if tree is not None and any(_drops_volumes(node) for node in ast.walk(tree)):
            found.add(rel)
    return frozenset(found)


def removals(graph: SourceGraph) -> frozenset[str]:
    """
    Args:
        graph: the source files to search.

    Returns:
        :func:`stack_calls` for :data:`REMOVAL`: the files that take the whole
        stack down; :func:`volume_removals` names those that drop part of it.
    """
    return stack_calls(graph, REMOVAL)


def starts(graph: SourceGraph) -> frozenset[str]:
    """
    Args:
        graph: the source files to search.

    Returns:
        :func:`stack_calls` for :data:`START`.
    """
    return stack_calls(graph, START)


def start_sites(graph: SourceGraph) -> dict[str, frozenset[str]]:
    """
    Args:
        graph: the source files to search.

    Returns:
        Per stack whose start a file-level graph can tell apart, the files
        that start it: :data:`DEPLOY` through :func:`starts`,
        :data:`TEST_RUNNER` through a call of ``infinito_test_runner_exec``.
    """
    runner = frozenset(
        rel
        for rel in graph.files
        if rel.endswith(".sh") and RUNNER_START.search(graph.text(rel))
    )
    return {DEPLOY: starts(graph), TEST_RUNNER: runner}
