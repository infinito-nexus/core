"""Roles a deploy may run, read statically from task files.

A role invokes another role when an ``include_role``/``import_role`` names it
(literally, through a literal loop item, or through a template whose literal
part narrows a glob), when one of its tasks hands a role name to an include
as a ``vars`` value (``load_app_id``, ``list_or_shoot_roles``), and when it
includes a task or handler file of that role by path. A role that includes
a bare template no loop resolves invokes every role its ``vars`` and
``defaults`` name in quotes.

Conditions inside roles are ignored, so :func:`deploy_closure` returns every
role a deploy may run, a superset of the roles it will run. The play's stage
files are the one exception: a group-membership gate there
(``'<role>' in group_names``, ``'<role>' | application_allowed(...)``) is
decided against the host, because it is what selects the host's roles.
"""

from __future__ import annotations

import fnmatch
import re
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.in_group_deps import reachable_roles

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

INCLUDE_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "include_role",
        "import_role",
        "ansible.builtin.include_role",
        "ansible.builtin.import_role",
    }
)
TASK_FILE_DIRS: tuple[str, ...] = ("tasks", "handlers")
TEMPLATE_DIRS: tuple[str, ...] = ("vars", "defaults")
LOOP_KEYS: tuple[str, ...] = ("loop", "with_items", "with_list")
NESTED_KEYS: tuple[str, ...] = ("block", "rescue", "always")
STAGES_DIR = Path("tasks") / "stages"
CONSTRUCTOR_STAGE = "01_constructor.yml"
DESTRUCTOR_STAGE = "03_destructor.yml"

_ROLE_FILE_REF_RE = re.compile(r"roles/(?P<role>[a-z0-9-]+)/(?:tasks|handlers)/")
_QUOTED_NAME_RE = re.compile(r"['\"](?P<name>[a-z0-9][a-z0-9-]*)['\"]")
_TEMPLATE_RE = re.compile(r"\{\{.*?\}\}")
_MEMBERSHIP_GATE_RE = re.compile(
    r"^'(?P<role>[a-z0-9-]+)'\s*(?P<test>in\s+group_names|\|\s*application_allowed\b)"
)


@cache
def role_names(roles_dir: str) -> frozenset[str]:
    """Return the name of every role directory under *roles_dir*."""
    root = Path(roles_dir)
    if not root.is_dir():
        return frozenset()
    return frozenset(path.name for path in root.iterdir() if path.is_dir())


def iter_tasks(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every task of a task list, descending into blocks."""
    if not isinstance(node, list):
        return
    for task in node:
        if not isinstance(task, dict):
            continue
        yield task
        for key in NESTED_KEYS:
            yield from iter_tasks(task.get(key))


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _named(name: str, known: frozenset[str]) -> set[str] | None:
    name = name.strip()
    if "{{" not in name:
        return {name}
    pattern = _TEMPLATE_RE.sub("*", name)
    if not pattern.strip("*"):
        return None
    return set(fnmatch.filter(known, pattern))


def _looped(task: dict[str, Any]) -> set[str] | None:
    for key in LOOP_KEYS:
        if key not in task:
            continue
        items = task[key]
        if not isinstance(items, list):
            return None
        found: set[str] = set()
        for item in items:
            if isinstance(item, str):
                found.add(item.strip())
            elif isinstance(item, dict):
                found.update(
                    str(item[field]).strip()
                    for field in ("role", "name")
                    if isinstance(item.get(field), str)
                )
        return found
    return None


def task_invocations(
    task: dict[str, Any], known: frozenset[str]
) -> tuple[set[str], bool]:
    """Return the roles one task invokes, and whether a name stayed unresolved.

    Args:
        task: one task mapping; the tasks nested in its blocks are not read.
        known: every existing role name.
    """
    own = {key: value for key, value in task.items() if key not in NESTED_KEYS}
    invoked = {value.strip() for value in _strings(own.get("vars"))} & known
    for value in _strings(own):
        invoked.update(
            match.group("role") for match in _ROLE_FILE_REF_RE.finditer(value)
        )

    unresolved = False
    for key in INCLUDE_ROLE_KEYS & own.keys():
        spec = own[key]
        name = spec.get("name") if isinstance(spec, dict) else spec
        named = _named(name, known) if isinstance(name, str) else None
        if named is None:
            named = _looped(own)
        if named is None:
            unresolved = True
            continue
        invoked |= named
    return invoked & known, unresolved


def file_invocations(path: Path, known: frozenset[str]) -> tuple[set[str], bool]:
    """Return the roles one task file invokes, and whether a name stayed unresolved.

    Args:
        path: a task or handler file.
        known: every existing role name.
    """
    invoked: set[str] = set()
    unresolved = False
    for task in iter_tasks(load_yaml_any(str(path), default_if_missing=None)):
        roles, open_name = task_invocations(task, known)
        invoked |= roles
        unresolved = unresolved or open_name
    return invoked, unresolved


def _files(role_dir: Path, subdirs: Iterable[str]) -> list[Path]:
    return sorted(
        path
        for sub in subdirs
        if (role_dir / sub).is_dir()
        for path in (role_dir / sub).rglob("*.yml")
    )


@cache
def role_invocations(roles_dir: str, role: str) -> frozenset[str]:
    """Return every other role *role* may invoke.

    Args:
        roles_dir: directory holding the role folders.
        role: role name.
    """
    known = role_names(roles_dir)
    role_dir = Path(roles_dir) / role
    invoked: set[str] = set()
    unresolved = False
    for path in _files(role_dir, TASK_FILE_DIRS):
        roles, open_name = file_invocations(path, known)
        invoked |= roles
        unresolved = unresolved or open_name
    if unresolved:
        for path in _files(role_dir, TEMPLATE_DIRS):
            invoked.update(
                match.group("name")
                for match in _QUOTED_NAME_RE.finditer(read_text(str(path)))
            )
    invoked.discard(role)
    return frozenset(invoked & known)


def stage_files(project_root: Path, host_types: Iterable[str]) -> list[Path]:
    """Return the play's stage files a host with *host_types* runs, in order.

    Args:
        project_root: repository root.
        host_types: the host's deployment types (``server``, ``workstation``).
    """
    stages = Path(project_root) / STAGES_DIR
    names = [
        CONSTRUCTOR_STAGE,
        *(f"02_{host_type}.yml" for host_type in host_types),
        DESTRUCTOR_STAGE,
    ]
    return [stages / name for name in names if (stages / name).is_file()]


def _gate_closed(
    task: dict[str, Any], seeds: frozenset[str], group_names: frozenset[str]
) -> bool:
    when = task.get("when")
    for condition in when if isinstance(when, list) else [when]:
        if not isinstance(condition, str):
            continue
        match = _MEMBERSHIP_GATE_RE.match(condition.strip())
        if match is None:
            continue
        members = group_names if match.group("test").startswith("in") else seeds
        if match.group("role") not in members:
            return True
    return False


def _open_tasks(
    node: Any, seeds: frozenset[str], group_names: frozenset[str]
) -> Iterator[dict[str, Any]]:
    if not isinstance(node, list):
        return
    for task in node:
        if not isinstance(task, dict) or _gate_closed(task, seeds, group_names):
            continue
        yield task
        for key in NESTED_KEYS:
            yield from _open_tasks(task.get(key), seeds, group_names)


def stage_invocations(
    path: Path,
    known: frozenset[str],
    *,
    seeds: Iterable[str],
    group_names: Iterable[str],
) -> set[str]:
    """Return the roles a stage file invokes on one host.

    Args:
        path: a file under ``tasks/stages/``.
        known: every existing role name.
        seeds: the application roles the host deploys.
        group_names: the host's inventory groups.
    """
    doc = load_yaml_any(str(path), default_if_missing=None)
    invoked: set[str] = set()
    for task in _open_tasks(doc, frozenset(seeds), frozenset(group_names)):
        invoked |= task_invocations(task, known)[0]
    return invoked


def deploy_closure(
    applications: dict[str, Any],
    seeds: Iterable[str],
    *,
    project_root: Path,
    host_types: Iterable[str],
    group_names: Iterable[str],
) -> set[str]:
    """Return every role a deploy may run on one host.

    Args:
        applications: the merged applications map, for service edges.
        seeds: the application roles the host deploys.
        project_root: repository root.
        host_types: the host's deployment types, selecting its stage files.
        group_names: the host's inventory groups.
    """
    known = role_names(str(Path(project_root) / "roles"))
    seed_set = {str(seed) for seed in seeds}
    roots = set(seed_set)
    for path in stage_files(project_root, host_types):
        roots |= stage_invocations(path, known, seeds=seed_set, group_names=group_names)
    return expand_roles(applications, roots, project_root=project_root)


def expand_roles(
    applications: dict[str, Any], roles: Iterable[str], *, project_root: Path
) -> set[str]:
    """Return *roles* plus every role they reach, transitively.

    Edges are ``meta/main.yml`` dependencies, the service edges of
    *applications*, and :func:`role_invocations`.

    Args:
        applications: the merged applications map; empty for no service edges.
        roles: the roles to start from.
        project_root: repository root.
    """
    roles_dir = str(Path(project_root) / "roles")
    known = role_names(roles_dir)
    frontier = {str(role) for role in roles}
    reached: set[str] = set()
    while frontier:
        expanded = (
            reachable_roles(
                applications,
                sorted(frontier),
                project_root=str(project_root),
                roles_dir=roles_dir,
            )
            | frontier
        ) - reached
        reached |= expanded
        frontier = {
            invoked
            for role in expanded & known
            for invoked in role_invocations(roles_dir, role)
        } - reached
    return reached
