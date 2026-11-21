from __future__ import annotations

import ast
import posixpath
import re
from pathlib import PurePath
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.stacks.makefile import make_calls

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

SOURCE_DIRS = ("cli/", "scripts/", "utils/")
SOURCE_SUFFIXES = (".py", ".sh")
SHELLCHECK_SOURCE = "# shellcheck source="
PATH_REF = re.compile(r"(?<![\w.-])((?:[\w.-]+/)*[\w-][\w.-]*\.(?:sh|py))(?!\w)")
MODULE_REF = re.compile(r"(?<![\w-])-m\s+([A-Za-z_]\w*(?:\.\w+)*)(?:\s+([a-z][\w-]*))?")
MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.\w+)+$")
PRINTED_HEREDOC = re.compile(r"\bcat\b[^<|;]*<<-?\s*['\"]?([A-Za-z_]\w*)")


def _strings(tree: ast.AST) -> list[str]:
    found: list[str] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
        pending.extend(ast.iter_child_nodes(node))
    return found


def _attribute_chains(tree: ast.AST) -> list[str]:
    found: list[str] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if not isinstance(node, ast.Attribute):
            pending.extend(ast.iter_child_nodes(node))
            continue
        parts = [node.attr]
        inner = node.value
        while isinstance(inner, ast.Attribute):
            parts.append(inner.attr)
            inner = inner.value
        if isinstance(inner, ast.Name):
            found.append(".".join([inner.id, *reversed(parts)]))
        else:
            pending.append(inner)
    return found


def _type_checking(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
    )


def _imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    found: list[ast.Import | ast.ImportFrom] = []
    pending: list[ast.AST] = [tree]
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append(node)
        elif _type_checking(node):
            pending.extend(node.orelse)
        else:
            pending.extend(ast.iter_child_nodes(node))
    return found


def _subcommand_names(tree: ast.AST) -> set[str]:
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_parser"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


class SourceGraph:
    """
    Args:
        files: the repository-relative paths of every source file.
        read: returns the text of one of ``files``.
    """

    def __init__(self, files: Iterable[str], read: Callable[[str], str]) -> None:
        self._files = frozenset(files)
        self._read = read
        self._modules: dict[str, str] = {}
        for rel in sorted(self._files):
            if rel.endswith(".py"):
                parts = rel[: -len(".py")].split("/")
                if parts[-1] == "__init__":
                    parts.pop()
                self._modules[".".join(parts)] = rel
        self._edges: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        self._trees: dict[str, ast.AST | None] = {}

    @property
    def files(self) -> frozenset[str]:
        """
        Returns:
            Every source file of the graph.
        """
        return self._files

    def rewritten(self, texts: Mapping[str, str]) -> SourceGraph:
        """
        Args:
            texts: replacement texts of some source files.

        Returns:
            The same graph, reading ``texts`` for those files.
        """
        return SourceGraph(
            self._files, lambda rel: texts[rel] if rel in texts else self._read(rel)
        )

    def text(self, rel: str) -> str:
        """
        Args:
            rel: one source file.
        """
        return self._read(rel)

    def tree(self, rel: str) -> ast.AST | None:
        """
        Args:
            rel: one Python source file.

        Returns:
            Its syntax tree, or ``None`` when it does not parse.
        """
        return self._tree(rel)

    def _tree(self, rel: str) -> ast.AST | None:
        if rel not in self._trees:
            try:
                self._trees[rel] = ast.parse(self._read(rel), filename=rel)
            except SyntaxError:
                self._trees[rel] = None
        return self._trees[rel]

    def _resolve(self, rel: str, ref: str, *, prefixed: bool) -> str | None:
        local = posixpath.normpath(posixpath.join(posixpath.dirname(rel), ref))
        rooted = posixpath.normpath(ref)
        anchored = [
            ref[index:]
            for index in (ref.find(prefix) for prefix in SOURCE_DIRS)
            if index > 0 and ref[index - 1] == "/"
        ]
        order = (local, rooted) if prefixed else (rooted, local)
        return next((path for path in (*order, *anchored) if path in self._files), None)

    def _imported(self, dotted: str) -> set[str]:
        parts = dotted.split(".")
        for depth in range(len(parts), 0, -1):
            name = ".".join(parts[:depth])
            if name in self._modules:
                return {self._modules[name]}
        return set()

    def _subcommand(self, package: str, word: str) -> set[str]:
        direct = f"{package}.{word.replace('-', '_')}"
        if direct in self._modules:
            return self._imported(direct)
        inside = f"{package}."
        return {
            rel
            for name, rel in self._modules.items()
            if name.startswith(inside)
            and word in _subcommand_names(self._tree(rel) or ast.Module(body=[]))
        }

    def _run(self, dotted: str, word: str | None) -> set[str]:
        found = self._imported(dotted)
        main = f"{dotted}.__main__"
        if main in self._modules:
            found |= self._imported(main)
        if word and self._modules.get(dotted, "").endswith("__init__.py"):
            found |= self._subcommand(dotted, word)
        return found

    def line_files(self, rel: str, line: str) -> set[str]:
        """
        Args:
            rel: the file holding the line, which relative paths resolve against.
            line: one line of shell or recipe text.

        Returns:
            The source files the line names by path or runs as ``-m`` module.
        """
        found = {
            path
            for match in PATH_REF.finditer(line)
            if (
                path := self._resolve(
                    rel,
                    match.group(1),
                    prefixed=line[max(match.start() - 1, 0) : match.start()] == "/",
                )
            )
        }
        for match in MODULE_REF.finditer(line):
            found |= self._run(match.group(1), match.group(2))
        return found

    def _shell(self, rel: str, text: str) -> tuple[set[str], set[str]]:
        files: set[str] = set()
        targets: set[str] = set()
        printed = ""
        for line in text.splitlines():
            stripped = line.lstrip()
            if printed:
                printed = "" if stripped == printed else printed
                continue
            if stripped.startswith("#") and not stripped.startswith(SHELLCHECK_SOURCE):
                continue
            heredoc = PRINTED_HEREDOC.search(line)
            printed = heredoc.group(1) if heredoc else ""
            files |= self.line_files(rel, line.replace(SHELLCHECK_SOURCE, " "))
            targets |= make_calls(line)
        return files, targets

    def _python(self, rel: str) -> set[str]:
        tree = self._tree(rel)
        if tree is None:
            return set()
        module = ".".join(rel[: -len(".py")].split("/"))
        anchor = module.split(".")[:-1]
        found: set[str] = set()
        bound: set[str] = set()
        for node in _imports(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found |= self._imported(alias.name)
                    if alias.asname is None and "." in alias.name:
                        bound.add(alias.name.split(".")[0])
                continue
            keep = max(len(anchor) - (node.level - 1), 0) if node.level else 0
            base = ".".join(
                [*anchor[:keep], *([node.module] if node.module else [])]
                if node.level
                else [node.module or ""]
            )
            for alias in node.names:
                submodule = f"{base}.{alias.name}"
                found |= self._imported(
                    submodule if submodule in self._modules else base
                )
        if bound:
            for chain in _attribute_chains(tree):
                if chain.split(".")[0] in bound:
                    found |= self._imported(chain)
        for value in _strings(tree):
            if MODULE_NAME.match(value) and value in self._modules:
                found |= self._run(value, None)
            else:
                found |= self.line_files(rel, value)
        found.discard(rel)
        return found

    def edges(self, rel: str) -> tuple[frozenset[str], frozenset[str]]:
        """
        Args:
            rel: one source file.

        Returns:
            The source files it reaches directly, and the make targets it runs.
        """
        if rel not in self._edges:
            if rel.endswith(".sh"):
                files, targets = self._shell(rel, self._read(rel))
            else:
                files, targets = self._python(rel), set()
            self._edges[rel] = (frozenset(files), frozenset(targets))
        return self._edges[rel]


def source_graph() -> SourceGraph:
    """
    Returns:
        The graph over every shell and Python file below :data:`SOURCE_DIRS`.
    """
    paths = {
        rel: path
        for path in iter_project_files(extensions=SOURCE_SUFFIXES)
        if (rel := PurePath(path).relative_to(PROJECT_ROOT).as_posix()).startswith(
            SOURCE_DIRS
        )
    }
    return SourceGraph(paths, lambda rel: read_text(paths[rel]))
