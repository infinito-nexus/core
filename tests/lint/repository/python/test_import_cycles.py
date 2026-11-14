from __future__ import annotations

import ast
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT


def _packages(root: Path) -> frozenset[str]:
    """
    Args:
        root: the repository root.

    Returns:
        The top-level directories that are Python packages.
    """
    return frozenset(init.parent.name for init in root.glob("*/__init__.py"))


def _module_name(rel: Path) -> tuple[str, bool]:
    """
    Args:
        rel: the file's path relative to the repository root.

    Returns:
        The dotted name of a module and whether it is a package.
    """
    parts = list(rel.with_suffix("").parts)
    package = parts[-1] == "__init__"
    if package:
        parts.pop()
    return ".".join(parts), package


def _guarded(node: ast.If) -> bool:
    """
    Args:
        node: the ``if`` statement.

    Returns:
        Whether an ``if`` body runs only when the module executes as ``__main__``.
    """
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and any(
            isinstance(c, ast.Constant) and c.value == "__main__"
            for c in test.comparators
        )
    )


def _statements(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """
    Args:
        tree: the parsed module.

    Returns:
        Every import statement that can run, at any depth.
    """
    found: list[ast.Import | ast.ImportFrom] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif isinstance(node, ast.If) and _guarded(node):
            pending.extend(node.orelse)
        else:
            pending.extend(ast.iter_child_nodes(node))
    return found


def _base(node: ast.ImportFrom, module: str, package: bool) -> str:
    """
    Args:
        node: the statement.
        module: dotted name of the importing module.
        package: whether the importing module is a package.

    Returns:
        The dotted name, empty when a relative import climbs above the tree.
    """
    if not node.level:
        return node.module or ""
    anchor = module.split(".") if package else module.split(".")[:-1]
    keep = len(anchor) - (node.level - 1)
    if keep <= 0:
        return ""
    return ".".join([*anchor[:keep], *([node.module] if node.module else [])])


def _targets(
    node: ast.Import | ast.ImportFrom, module: str, package: bool, known: set[str]
) -> list[str]:
    """
    Args:
        node: the statement.
        module: dotted name of the importing module.
        package: whether the importing module is a package.
        known: every module of the tree.

    Returns:
        Each module the statement names, plus every package above it, whose
        ``__init__`` runs first.
    """
    found: set[str] = set()
    if isinstance(node, ast.Import):
        found = {alias.name for alias in node.names if alias.name in known}
    else:
        base = _base(node, module, package)
        for alias in node.names if base else ():
            submodule = f"{base}.{alias.name}"
            if submodule in known:
                found.add(submodule)
            elif base in known:
                found.add(base)
    parents = {
        ".".join(parts[:depth])
        for parts in (target.split(".") for target in found)
        for depth in range(1, len(parts))
    }
    return sorted(found | (parents & known))


def _edges(
    sources: dict[str, tuple[str, bool, str]],
) -> list[tuple[str, str, str, int]]:
    """
    Args:
        sources: dotted module name to its path, package flag and text.

    Returns:
        ``(importer, imported, path, line)`` per statement and target; a module
        importing itself or one of its own parent packages adds nothing.
    """
    known = set(sources)
    edges: list[tuple[str, str, str, int]] = []
    for module, (rel, package, content) in sources.items():
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for node in _statements(tree):
            edges.extend(
                (module, target, rel, node.lineno)
                for target in _targets(node, module, package, known)
                if target != module and not module.startswith(f"{target}.")
            )
    return edges


def _components(graph: dict[str, set[str]]) -> list[set[str]]:
    """
    Args:
        graph: importer to the modules it imports.

    Returns:
        The strongly connected components that hold more than one module.
    """
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[set[str]] = []
    for start in sorted(graph):
        if start in index:
            continue
        index[start] = low[start] = len(index)
        stack.append(start)
        on_stack.add(start)
        work = [(start, iter(sorted(graph[start])))]
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is not None:
                if child not in index:
                    index[child] = low[child] = len(index)
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(graph.get(child, ())))))
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] != index[node]:
                continue
            component: set[str] = set()
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.add(member)
                if member == node:
                    break
            if len(component) > 1:
                found.append(component)
    return found


def _cycles(sources: dict[str, tuple[str, bool, str]]) -> list[list[str]]:
    """
    Args:
        sources: dotted module name to its path, package flag and text.

    Returns:
        One list per component: its members, then ``path:line: a -> b`` for
        every import inside it.
    """
    edges = _edges(sources)
    graph: dict[str, set[str]] = {module: set() for module in sources}
    for importer, imported, _rel, _line in edges:
        graph[importer].add(imported)
    report: list[list[str]] = []
    for component in _components(graph):
        inside = sorted(
            f"{rel}:{line}: {importer} -> {imported}"
            for importer, imported, rel, line in edges
            if importer in component and imported in component
        )
        report.append([" <-> ".join(sorted(component)), *inside])
    return sorted(report)


def _sources(root: Path) -> dict[str, tuple[str, bool, str]]:
    """
    Args:
        root: the repository root.

    Returns:
        Every module of the repository's own packages.
    """
    packages = _packages(root)
    sources: dict[str, tuple[str, bool, str]] = {}
    for path in iter_non_ignored_files(extensions=(".py",)):
        rel = Path(path).relative_to(root)
        if rel.parts[0] not in packages:
            continue
        try:
            content = read_text(str(path))
        except (OSError, UnicodeDecodeError):
            continue
        name, package = _module_name(rel)
        sources[name] = (rel.as_posix(), package, content)
    return sources


class TestImportCycles(unittest.TestCase):
    def test_no_repository_module_imports_into_a_cycle(self) -> None:
        cycles = _cycles(_sources(PROJECT_ROOT))
        statements = sum(len(cycle) - 1 for cycle in cycles)
        report = "\n".join(
            f"  - {cycle[0]}\n" + "\n".join(f"      {edge}" for edge in cycle[1:])
            for cycle in cycles
        )
        self.assertFalse(
            cycles,
            f"{len(cycles)} import cycle(s) through {statements} import "
            f"statement(s):\n{report}\n\n"
            "Move what both sides need into the lower module, or into a new "
            "module both import, so neither has to defer its import.",
        )


def _source(text: str, package: bool = False) -> tuple[str, bool, str]:
    """
    Args:
        text: the module's source.
        package: whether the module is a package.

    Returns:
        A test module entry.
    """
    return ("m.py", package, text)


class TestCycleDetection(unittest.TestCase):
    def test_a_module_level_pair_is_reported(self) -> None:
        cycles = _cycles(
            {"p.a": _source("import p.b"), "p.b": _source("from p.a import x")}
        )

        self.assertEqual(
            [["p.a <-> p.b", "m.py:1: p.a -> p.b", "m.py:1: p.b -> p.a"]], cycles
        )

    def test_a_deferred_import_still_closes_the_cycle(self) -> None:
        sources = {
            "p.a": _source("import p.b"),
            "p.b": _source("def f():\n    from p.a import x"),
        }

        self.assertEqual(["p.a <-> p.b"], [c[0] for c in _cycles(sources)])

    def test_a_type_checking_import_closes_the_cycle(self) -> None:
        sources = {
            "p.a": _source("import p.b"),
            "p.b": _source("if TYPE_CHECKING:\n    from p.a import X"),
        }

        self.assertEqual(["p.a <-> p.b"], [c[0] for c in _cycles(sources)])

    def test_importing_a_submodule_also_imports_its_package(self) -> None:
        sources = {
            "pp": _source("from xx import f", package=True),
            "pp.s": _source("G = 1"),
            "xx": _source("from pp.s import G"),
        }

        self.assertEqual(
            [["pp <-> xx", "m.py:1: pp -> xx", "m.py:1: xx -> pp"]], _cycles(sources)
        )

    def test_a_plain_submodule_import_also_imports_its_package(self) -> None:
        sources = {
            "pp": _source("import xx", package=True),
            "pp.s": _source("G = 1"),
            "xx": _source("def f():\n    import pp.s"),
        }

        self.assertEqual(["pp <-> xx"], [c[0] for c in _cycles(sources)])

    def test_a_main_guard_import_is_skipped(self) -> None:
        sources = {
            "p.a": _source("import p.b"),
            "p.b": _source('if __name__ == "__main__":\n    import p.a'),
        }

        self.assertEqual([], _cycles(sources))

    def test_a_relative_import_resolves_inside_the_package(self) -> None:
        sources = {
            "q.p.a": _source("from .b import x"),
            "q.p.b": _source("from ..r import y"),
            "q.r": _source("from .p.a import z"),
        }

        self.assertEqual(["q.p.a <-> q.p.b <-> q.r"], [c[0] for c in _cycles(sources)])

    def test_a_submodule_named_by_from_import_is_the_target(self) -> None:
        sources = {
            "p": _source("", package=True),
            "p.a": _source("from p import b"),
            "p.b": _source("from p.a import x"),
        }

        self.assertEqual(["p.a <-> p.b"], [c[0] for c in _cycles(sources)])

    def test_a_submodule_reading_its_parent_package_is_left_out(self) -> None:
        sources = {
            "p": _source("ROOT = 1\nfrom . import a", package=True),
            "p.a": _source("from . import ROOT"),
        }

        self.assertEqual([], _cycles(sources))

    def test_a_longer_cycle_lists_every_member(self) -> None:
        sources = {
            "p.a": _source("import p.b"),
            "p.b": _source("import p.c"),
            "p.c": _source("import p.a"),
        }

        self.assertEqual(["p.a <-> p.b <-> p.c"], [c[0] for c in _cycles(sources)])

    def test_an_acyclic_graph_and_foreign_imports_pass(self) -> None:
        sources = {
            "p.a": _source("import os\nimport p.b"),
            "p.b": _source("import yaml\nfrom p.c import x"),
        }

        self.assertEqual([], _cycles(sources))


if __name__ == "__main__":
    unittest.main()
