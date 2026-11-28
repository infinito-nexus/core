"""Map every changed path to what it reaches: seed roles, tests, the full set
or nothing a deploy runs.

The rule of the classifier: a path it cannot model widens to the full set,
never to nothing. Narrowing comes only from the rules that can prove it: a
role path seeds its role, a format-only edit (same AST, same loaded YAML or
JSON) reaches nothing, a test or a document runs no deploy, and a shared
symbol (a plugin name, a module, a group_vars key) reaches the roles the
symbol index finds consuming it. A role file adds every unit test that names
the role, as a unit test reading the real roles tree does; a path that reaches the
full set keeps the tests the walk found before it widened and its mirrored
unit test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import yaml

from cli.meta.ci.iterate import surface
from cli.meta.ci.iterate.equivalence import directives_changed, equivalent
from cli.meta.ci.iterate.names import (
    MODULE,
    NAME,
    is_test_file,
    module_name,
    plugin_names,
    start_symbols,
)
from utils.cache.yaml import load_yaml_all_str

if TYPE_CHECKING:
    from collections.abc import Callable

    from cli.meta.ci.iterate.symbols import Index

SEED = "seed"
DOC_SEED = "doc-seed"
TESTS = "tests"
NONE = "none"
FULL = "full"

_PARSED = (".py", ".yml", ".yaml", ".json")
LINT_SUITE = "tests/lint"


class Change(NamedTuple):
    """What one changed path reaches.

    Attributes:
        path: repository-relative POSIX path.
        kind: where it sits (a :mod:`cli.meta.ci.iterate.surface` kind).
        effect: ``seed`` (its roles redeploy with their consumers),
            ``doc-seed`` (a role's own document: only that role replays it),
            ``tests`` (only tests run), ``none`` (no deploy and no test) or
            ``full`` (every deploy).
        roles: the seed roles.
        tests: the test files and directories it adds to T0.
        reason: why, in one line.
        format_only: the edit changes no meaning.
        targets: the tooling make targets that run it, for T0.
    """

    path: str
    kind: str
    effect: str
    roles: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    reason: str = ""
    format_only: bool = False
    targets: tuple[str, ...] = ()


def _yaml_keys(text: str | None) -> dict | None:
    if text is None:
        return {}
    try:
        documents = load_yaml_all_str(text)
    except yaml.YAMLError:
        return None
    merged: dict = {}
    for document in documents:
        if document is None:
            continue
        if not isinstance(document, dict):
            return None
        merged.update(document)
    return merged


def changed_keys(old: str | None, new: str | None) -> set[str] | None:
    """Return the top-level keys whose value differs between two YAML texts.

    Returns:
        None when a side does not parse into a mapping.
    """
    before, after = _yaml_keys(old), _yaml_keys(new)
    if before is None or after is None:
        return None
    return {
        str(key)
        for key in before.keys() | after.keys()
        if before.get(key, ...) != after.get(key, ...)
    }


def _mirror_test(path: str) -> str:
    head, _, name = path.rpartition("/")
    stem = name[: -len(".py")]
    target = f"tests/unit/python/{head}" if head else "tests/unit/python"
    return f"{target}/test_{stem}.py" if stem != "__init__" else target


def _test_target(path: str) -> str:
    return path if is_test_file(path) else path.rpartition("/")[0]


def _format_only(path: str, kind: str, old: str | None, new: str | None) -> Change:
    if directives_changed(old, new):
        return Change(
            path, kind, TESTS, (), (LINT_SUITE,), "lint directive changed", True
        )
    return Change(path, kind, NONE, reason="format-only", format_only=True)


def _symbol_change(path: str, kind: str, start: set, index: Index) -> Change:
    reach = index.reach(start)
    tests = tuple(sorted(reach.tests))
    targets = tuple(sorted(reach.targets))
    if reach.full:
        why = f"reaches every deploy: {reach.full}"
        return Change(path, kind, FULL, (), tests, why, targets=targets)
    if not reach.roles:
        why = "no role consumes it" + (
            f"; tooling: {len(reach.tooling)} file(s)" if reach.tooling else ""
        )
        effect = TESTS if tests or targets else NONE
        return Change(path, kind, effect, (), tests, why, targets=targets)
    trail = "; ".join(f"{role} via {via}" for role, via in sorted(reach.roles.items()))
    roles = tuple(sorted(reach.roles))
    return Change(path, kind, SEED, roles, tests, trail, targets=targets)


def classify(
    path: str,
    read: Callable[[str], tuple[str | None, str | None]],
    index: Index,
    exists: Callable[[str], bool],
) -> Change:
    """Return what one changed path reaches.

    Args:
        path: repository-relative POSIX path.
        read: returns the ``(base, head)`` contents of a path, None for a side
            where it does not exist.
        index: the symbol index over the current tree.
        exists: whether a repository-relative path exists in the current tree,
            used to add the mirrored unit test of a module to T0.
    """
    where = surface.place(path)
    old, new = read(path) if path.endswith(_PARSED) else (None, None)
    if (
        where.kind in (surface.ROLE, surface.PLUGIN)
        and where.role
        and equivalent(path, old, new)
    ):
        return _format_only(path, where.kind, old, new)
    if where.kind == surface.ROLE:
        if path.endswith(surface.DOC_SUFFIXES):
            return Change(
                path, where.kind, DOC_SEED, (where.role,), (), "role document"
            )
        tests = tuple(sorted(index.tests_naming(where.role)))
        return Change(path, where.kind, SEED, (where.role,), tests, "role file")
    if where.kind == surface.TEST:
        if is_test_file(path):
            return Change(path, where.kind, TESTS, (), (path,), "test")
        change = _symbol_change(path, where.kind, start_symbols(path), index)
        return change._replace(
            effect=TESTS if change.effect == NONE else change.effect,
            tests=change.tests or (_test_target(path),),
            reason=f"test helper: {change.reason}",
        )
    if where.kind == surface.DOCS:
        return Change(path, where.kind, NONE, reason="document, no deploy reads it")
    if where.kind in (surface.GLOBAL, surface.WORKFLOW, surface.UNKNOWN):
        return Change(path, where.kind, FULL, reason=f"{where.kind} path")
    if equivalent(path, old, new):
        return _format_only(path, where.kind, old, new)
    if where.kind == surface.GROUP_VARS:
        keys = changed_keys(old, new)
        if keys is None:
            return Change(path, where.kind, FULL, reason="group_vars that do not parse")
        return _symbol_change(path, where.kind, {(NAME, key) for key in keys}, index)
    if where.kind == surface.PLUGIN:
        names: set[str] = set()
        for text in (old, new):
            found = plugin_names(path, where.plugin, text) if text is not None else ()
            if found is None:
                return Change(path, where.kind, FULL, reason="plugin names not literal")
            names.update(found)
        dotted = module_name(path)
        start = {(NAME, name) for name in names} | (
            {(MODULE, dotted)} if dotted else set()
        )
        return _symbol_change(path, where.kind, start, index)
    change = _symbol_change(path, where.kind, start_symbols(path), index)
    mirror = _mirror_test(path) if path.endswith(".py") else ""
    if not mirror or not exists(mirror):
        return change
    tests = tuple(sorted({*change.tests, mirror}))
    effect = TESTS if change.effect == NONE else change.effect
    return change._replace(tests=tests, effect=effect)
