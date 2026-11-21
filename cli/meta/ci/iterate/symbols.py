"""Who consumes a shared symbol: the index behind every non-role path.

A changed module reaches whoever imports it, transitively, and whoever names
it as a string (``python -m utils.x`` in a task); a package's ``__main__``
answers to the package name. Any other file reaches whoever names its path,
by the repository path or a shorter tail of it, and its siblings that name
it by file name, and whoever builds a path into its directory from a variable
(``<dir>/${lint_type}.sh``); such a dispatcher passes the walk on only
to the lines that hand it the value naming the file. A plugin reaches whoever
calls one of its names; a group_vars key reaches whoever reads it, a key of
another group_vars file included. The walk ends at a role (a seed), a test
(T0), a Makefile target of :data:`TOOLING_TARGETS` (T0), deploy machinery, a
global deploy file, a workflow, any other Makefile target or a file of
unknown kind (the full set), and at tooling nobody names. Deploy machinery is
what the deploy targets run: :data:`surface.DEPLOY_MACHINERY` by its path and
every module or script a Makefile target outside :data:`TOOLING_TARGETS`
names, such as ``cli.meta.cache`` of ``make dotenv`` or
``cli.meta.ci.swarm_preflight`` of ``make swarm-zombie``.

The name search is a word match over the text, so a docstring or a comment
naming a symbol counts as a consumer: the index errs towards a wider plan,
never a narrower one. A plugin whose names cannot be read statically, or a
group_vars file that does not parse, widens to the full set for the same
reason.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from cli.meta.ci.iterate import surface
from cli.meta.ci.iterate.names import (
    MODULE,
    NAME,
    PACKAGE_FILES,
    PATH,
    is_test_file,
    module_name,
    path_words,
    plugin_names,
    start_symbols,
)
from utils.cache.files import read_text, repository_files
from utils.cache.yaml import load_yaml_all_str

if TYPE_CHECKING:
    from collections.abc import Iterable

CORPUS_DIRS = (
    "roles/",
    "group_vars/",
    "tasks/",
    "templates/",
    "playbooks/",
    "inventories/",
    "compose/",
    "plugins/",
    "library/",
    "utils/",
    "cli/",
    "scripts/",
    "tests/",
    "agents/",
    ".github/",
)
CORPUS_FILES = frozenset(
    {
        "playbook.yml",
        "playbook-sync.yml",
        "compose.yml",
        "Dockerfile",
        "Makefile",
        "ansible.cfg",
    }
)
CORPUS_SUFFIXES = (".yml", ".yaml", ".j2", ".py", ".sh", ".json", ".cfg", ".ini")
MODULE_UTILS = "ansible.module_utils."

FULL_CONSUMERS = (surface.GLOBAL, surface.WORKFLOW, surface.UNKNOWN)
MAKEFILE = "Makefile"
UNIT_TESTS = "tests/unit/"
TOOLING_TARGETS = (
    "autoformat",
    "bond",
    "clean-pycache-dirs",
    "console",
    "design-logos",
    "design-queue",
    "diagnose-",
    "iterate-plan",
    "lint",
    "lint-",
    "meta-",
    "test",
    "test-",
)
MAKE_TARGET = re.compile(r"^(?:\.PHONY:\s*([\w-]+)|([\w-]+)\s*:(?!=))")
INTERPOLATED = r"/(?:\$\{[^}\n]+\}|\$\w+)([\w.-]*)"


@dataclass
class Reach:
    """What one changed path reaches.

    Attributes:
        roles: every role whose own file consumes the path, mapped to the
            trail that leads there.
        tests: the test files that consume it.
        full: why the path reaches every deploy; empty when it does not.
        tooling: consumers no deploy runs.
        targets: the tooling make targets whose recipe names a consumer.
        bound: each consumer that builds a path by interpolation, mapped to
            the values it must take to name the walked file.
    """

    roles: dict[str, str] = field(default_factory=dict)
    tests: set[str] = field(default_factory=set)
    full: str = ""
    tooling: set[str] = field(default_factory=set)
    targets: set[str] = field(default_factory=set)
    bound: dict[str, set[str]] = field(default_factory=dict)


def _imported(tree: ast.AST, package: str) -> set[str]:
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*anchor, base] if base else anchor)
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names)
    return {
        "utils." + target[len(MODULE_UTILS) :]
        if target.startswith(MODULE_UTILS)
        else target
        for target in targets
        if target
    }


def _word(names: Iterable[str]) -> re.Pattern[str]:
    longest_first = sorted(names, key=lambda name: (-len(name), name))
    alternation = "|".join(re.escape(name) for name in longest_first)
    return re.compile(rf"(?<![\w.])(?:{alternation})(?![\w])")


def tooling_target(name: str) -> bool:
    """Return True for a make target no deploy runs (:data:`TOOLING_TARGETS`;
    an entry ending in ``-`` is a prefix).

    Args:
        name: the make target.
    """
    return any(
        name == entry or (entry.endswith("-") and name.startswith(entry))
        for entry in TOOLING_TARGETS
    )


def make_targets(text: str, pattern: re.Pattern[str], values: set[str]) -> set[str]:
    """Return the Makefile targets whose block has a line matching *pattern*.

    A block runs from a target's ``.PHONY`` line to the next one, so its
    comments count; a line above every target belongs to the empty name.

    Args:
        text: the Makefile.
        pattern: what a consuming line names.
        values: when not empty, a line counts only if it also names one of
            them, as the argument a dispatcher interpolates.
    """
    passed = _word(values) if values else None
    target = ""
    found: set[str] = set()
    for line in text.splitlines():
        head = MAKE_TARGET.match(line)
        if head:
            target = head.group(1) or head.group(2)
        if pattern.search(line) and (passed is None or passed.search(line)):
            found.add(target)
    return found


class Index:
    """The consumer index over one tree.

    Args:
        root: the repository root the corpus is read from.
        corpus: repository-relative paths to search; None takes every file
            git tracks or would track with a corpus suffix under a corpus
            directory, plus the root deploy files.
    """

    def __init__(self, root: Path, corpus: Iterable[str] | None = None) -> None:
        self.root = root
        self._corpus = None if corpus is None else tuple(corpus)
        self._imports: dict[str, set[str] | None] = {}

    @cached_property
    def corpus(self) -> tuple[str, ...]:
        if self._corpus is not None:
            return self._corpus
        return tuple(
            rel
            for rel in repository_files(untracked=True)
            if rel in CORPUS_FILES
            or (rel.startswith(CORPUS_DIRS) and rel.endswith(CORPUS_SUFFIXES))
        )

    def text(self, rel: str) -> str:
        """Return the content of a corpus file, empty when it cannot be read."""
        try:
            return read_text(str(self.root / rel))
        except (OSError, UnicodeDecodeError):
            return ""

    def imports(self, rel: str) -> set[str] | None:
        """Return the module names *rel* imports, None when it does not parse."""
        if rel not in self._imports:
            name = module_name(rel)
            stem = Path(rel).stem
            package = name if stem in PACKAGE_FILES else name.rpartition(".")[0]
            try:
                self._imports[rel] = _imported(ast.parse(self.text(rel)), package)
            except SyntaxError:
                self._imports[rel] = None
        return self._imports[rel]

    def importers(self, module: str) -> set[str]:
        """Return the Python files that import *module* or one of its submodules."""
        leaf = module.rpartition(".")[2]
        found: set[str] = set()
        for rel in self.corpus:
            if not rel.endswith(".py") or leaf not in self.text(rel):
                continue
            targets = self.imports(rel) or set()
            if any(t == module or t.startswith(module + ".") for t in targets):
                found.add(rel)
        return found

    def mentions(self, words: Iterable[str]) -> dict[str, set[str]]:
        """Return each corpus file that names one of *words*, with the words it names."""
        wanted = set(words)
        if not wanted:
            return {}
        pattern = _word(wanted)
        hits: dict[str, set[str]] = {}
        for rel in self.corpus:
            found = {match.group(0) for match in pattern.finditer(self.text(rel))}
            if found:
                hits[rel] = found
        return hits

    def siblings_naming(self, rel: str) -> set[str]:
        """Return the corpus files beside *rel* that name it by file name."""
        folder, _, name = rel.rpartition("/")
        pattern = _word([name])
        return {
            other
            for other in self.corpus
            if other != rel
            and other.rpartition("/")[0] == folder
            and pattern.search(self.text(other))
        }

    def segments_naming(self, rel: str) -> set[str]:
        """Return the corpus files that quote both the file name of *rel* and
        its directory name, as ``Path`` joins (``"github" / "x.sh"``) do."""
        folder, _, name = rel.rpartition("/")
        parent = folder.rpartition("/")[2]
        if not parent:
            return set()
        quoted = [
            re.compile(rf"[\"']{re.escape(part)}[\"']") for part in (name, parent)
        ]
        return {
            other
            for other in self.corpus
            if other != rel
            and name in self.text(other)
            and all(pattern.search(self.text(other)) for pattern in quoted)
        }

    def interpolations_naming(self, rel: str) -> dict[str, str]:
        """Return the corpus files that build a path into the directory of
        *rel* from a variable (``<dir>/${lint_type}.sh``), mapped to the
        value that names *rel*.

        Args:
            rel: repository-relative POSIX path.
        """
        folder, _, name = rel.rpartition("/")
        if not folder:
            return {}
        pattern = re.compile(rf"(?<![\w.-]){re.escape(folder)}{INTERPOLATED}")
        found: dict[str, str] = {}
        for other in self.corpus:
            if other == rel or f"{folder}/$" not in self.text(other):
                continue
            for match in pattern.finditer(self.text(other)):
                tail = match.group(1)
                if name.endswith(tail) and len(name) > len(tail):
                    found.setdefault(other, name[: len(name) - len(tail)])
        return found

    def tests_naming(self, role: str) -> set[str]:
        """Return the unit test files that name *role* by its path or, for a
        name with a dash, by its name: the unit tests that read its files from
        the real roles tree. Lint and integration tests naming it stay with
        the T2 gate.

        Args:
            role: the role name.
        """
        pattern = _word({f"roles/{role}", *((role,) if "-" in role else ())})
        return {
            rel
            for rel in self.corpus
            if rel.startswith(UNIT_TESTS)
            and is_test_file(rel)
            and pattern.search(self.text(rel))
        }

    def keys_naming(self, rel: str, pattern: re.Pattern[str]) -> set[str] | None:
        """Return the top-level keys of a group_vars file whose value matches.

        Returns:
            None when the file does not parse; the walk then widens.
        """
        try:
            documents = load_yaml_all_str(self.text(rel))
        except yaml.YAMLError:
            return None
        keys: set[str] = set()
        for document in documents:
            if not isinstance(document, dict):
                continue
            for key, value in document.items():
                if pattern.search(json.dumps(value, default=str)):
                    keys.add(str(key))
        return keys

    def reach(self, start: Iterable[tuple[str, str]]) -> Reach:
        """Walk from the symbols one changed path defines to their consumers.

        The defining file is searched like any other: a group_vars key read by
        a sibling key of its own file reaches that key's readers too, and a
        file naming its own symbols adds nothing the walk has not seen.

        Args:
            start: ``(kind, symbol)`` pairs: ``module`` with a dotted name,
                ``name`` with a plugin name or a group_vars key.
        """
        result = Reach()
        seen: set[tuple[str, str]] = set()
        frontier = set(start)
        while frontier and not result.full:
            seen |= frontier
            found: set[tuple[str, str]] = set()
            for consumer, why in self._consumers(frontier, result).items():
                found |= self._visit(consumer, why, result)
                if result.full:
                    break
            frontier = found - seen
        return result

    def _consumers(
        self, frontier: set[tuple[str, str]], result: Reach
    ) -> dict[str, tuple[set[str], str]]:
        hits: dict[str, tuple[set[str], str]] = {}
        words = {symbol for kind, symbol in frontier if kind == NAME}
        for kind, symbol in sorted(frontier):
            if kind == MODULE:
                words |= {symbol, symbol.replace(".", "/")}
                for rel in sorted(self.importers(symbol)):
                    hits.setdefault(rel, (set(), f"imports {symbol}"))[0].add(symbol)
            if kind == PATH:
                words |= path_words(symbol)
                name = symbol.rpartition("/")[2]
                for rel in sorted(self.siblings_naming(symbol)):
                    hits.setdefault(rel, (set(), f"names {name}"))[0].add(name)
                for rel in sorted(self.segments_naming(symbol)):
                    why = f"builds {symbol} from quoted segments"
                    hits.setdefault(rel, (set(), why))[0].add(name)
                for rel, value in sorted(self.interpolations_naming(symbol).items()):
                    why = f"builds {symbol} by interpolating {value}"
                    hits.setdefault(rel, (set(), why))[0].add(name)
                    result.bound.setdefault(rel, set()).add(value)
        for rel, named in sorted(self.mentions(words).items()):
            entry = hits.setdefault(rel, (set(), "names " + ", ".join(sorted(named))))
            entry[0].update(named)
        return hits

    def _visit(
        self, rel: str, why: tuple[set[str], str], result: Reach
    ) -> set[tuple[str, str]]:
        symbols, reason = why
        where = surface.place(rel)
        trail = f"{rel} {reason}"
        if where.kind == surface.ROLE:
            result.roles.setdefault(where.role, trail)
            return set()
        if where.kind == surface.TEST:
            if is_test_file(rel):
                result.tests.add(rel)
                return set()
            if rel.endswith("/conftest.py"):
                result.tests.add(rel.rpartition("/")[0])
            return start_symbols(rel)
        if rel == MAKEFILE:
            return self._visit_makefile(rel, symbols, trail, result)
        if where.kind in FULL_CONSUMERS:
            result.full = f"{trail}, which counts as {where.kind}"
            return set()
        if where.kind == surface.GROUP_VARS:
            keys = self.keys_naming(rel, _word(symbols))
            if keys is None:
                result.full = f"{trail}, which does not parse"
                return set()
            return {(NAME, key) for key in keys - symbols}
        if where.kind == surface.PLUGIN:
            names = plugin_names(rel, where.plugin, self.text(rel))
            if names is None:
                result.full = f"{trail}, whose plugin names are not literal"
                return set()
            dotted = module_name(rel)
            return {(NAME, n) for n in names} | (
                {(MODULE, dotted)} if dotted else set()
            )
        if where.kind == surface.TOOLING:
            result.tooling.add(rel)
        return start_symbols(rel)

    def _visit_makefile(
        self, rel: str, symbols: set[str], trail: str, result: Reach
    ) -> set[tuple[str, str]]:
        values = {
            value
            for dispatcher, bound in result.bound.items()
            if path_words(dispatcher) & symbols
            for value in bound
        }
        targets = make_targets(self.text(rel), _word(symbols), values)
        deploying = sorted(t for t in targets if not tooling_target(t))
        if deploying or not (targets or values):
            names = ", ".join(deploying) or "no target"
            result.full = f"{trail} in make {names}, which counts as {surface.UNKNOWN}"
            return set()
        result.targets |= targets
        return set()
