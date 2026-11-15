from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TASKS_MAIN,
)

from . import PROJECT_ROOT
from .test_stack_service_declared import STACK_ENTRY_RE

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

STACK_ROLE = "svc-stack"
BRIDGE = Path("tasks/utils/stack.yml")
CANONICAL_BRIDGE = Path("roles") / STACK_ROLE / "files/bridge.yml"
STACK_TASKS = Path("roles") / STACK_ROLE / "tasks"
CONSTRUCTOR = Path("tasks/stages/01_constructor.yml")
MAIN = Path(ROLE_FILE_TASKS_MAIN)
CORE = "00_core.yml"
RUN_ONCE_RE = re.compile(r"run_once_[a-z0-9_]+ is not defined")
LOADER = "sys-service-loader"
GROUP_SETUP = "tasks/utils/setup/group.yml"
ENTRY = "tasks/utils/load/entry.yml"
ENTRY_GATE = "STACK_ENTRY_PENDING"
ENTRY_SITES = (
    Path("tasks/utils/load/app.yml"),
    Path("tasks/utils/setup/role.yml"),
    Path("tasks/utils/sync/role.yml"),
    Path("roles/sys-service-loader/tasks/drain.yml"),
    Path("roles/sys-service-loader/tasks/list_or_shoot.yml"),
)
BATCH_FACTS = frozenset(
    {
        "front_proxy_batch_vhosts",
        "front_proxy_deferred_probes",
        "front_proxy_deferred_stale",
        "stack_batch_deferred",
        "stack_batch_deferring",
        "stack_batch_late",
        "stack_batch_plan",
        "stack_batch_running",
        "stack_front_served",
        "stack_matomo_unsited",
    }
)
SET_FACT = ("set_fact", "ansible.builtin.set_fact")
ROLE_INCLUDES = (
    "include_role",
    "import_role",
    "ansible.builtin.include_role",
    "ansible.builtin.import_role",
)
TASK_INCLUDES = (
    "include_tasks",
    "import_tasks",
    "ansible.builtin.include_tasks",
    "ansible.builtin.import_tasks",
)
BLOCK_KEYS = ("block", "rescue", "always")


def _tasks(node: Any) -> Iterator[dict]:
    """Args:
        node: a parsed task file, or a task list inside one.

    Returns:
        every task mapping in document order, the tasks of blocks included.
    """
    for task in node if isinstance(node, list) else []:
        if not isinstance(task, dict):
            continue
        yield task
        for key in BLOCK_KEYS:
            yield from _tasks(task.get(key))


def _mappings(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _mappings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _mappings(item)


def _role_include(task: dict) -> dict:
    for key in ROLE_INCLUDES:
        spec = task.get(key)
        if isinstance(spec, dict):
            return spec
    return {}


def _task_include(task: dict) -> str:
    for key in TASK_INCLUDES:
        spec = task.get(key)
        if isinstance(spec, dict):
            return str(spec.get("file", ""))
        if isinstance(spec, str):
            return spec
    return ""


def bridge_roles(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the roles that ship a stack bridge, in name order.
    """
    return sorted(
        path.relative_to(root / "roles").parts[0]
        for path in root.glob(f"roles/*/{BRIDGE}")
    )


def non_canonical_bridges(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the bridge roles whose bridge differs from the canonical text.
    """
    canonical = read_text(str(root / CANONICAL_BRIDGE))
    return [
        role
        for role in bridge_roles(root)
        if read_text(str(root / "roles" / role / BRIDGE)) != canonical
    ]


def bridges_beside_an_entry(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the bridge roles that still include an svc-stack consumer entry.
    """
    return [
        role
        for role in bridge_roles(root)
        if any(
            STACK_ENTRY_RE.search(read_text(str(path)))
            for path in (root / "roles" / role).glob("tasks/**/*.yml")
        )
    ]


def bootstrap_roles(root: Path) -> set[str]:
    """Args:
        root: the repository root.

    Returns:
        the roles the constructor enters before the shared-service loader,
        named literally or through a role group it sets up.
    """
    named: set[str] = set()
    groups: set[str] = set()
    for task in _tasks(load_yaml_any(str(root / CONSTRUCTOR))):
        name = str(_role_include(task).get("name", ""))
        if name == LOADER:
            break
        if name:
            named.add(name)
        if _task_include(task).endswith(GROUP_SETUP) and isinstance(
            task.get("loop"), list
        ):
            groups.update(str(group) for group in task["loop"])
    return {
        path.name
        for path in (root / "roles").iterdir()
        if path.name in named
        or any(path.name.startswith(f"{group}-") for group in groups)
    }


def _declares_stack(role_dir: Path) -> bool:
    services = load_yaml_any(
        str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
    )
    entry = services.get("stack") if isinstance(services, dict) else None
    return (
        isinstance(entry, dict)
        and entry.get("enabled") is True
        and entry.get("shared") is True
    )


def consumers_without_a_stack_path(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the roles besides svc-stack that declare ``stack`` enabled and shared
        but neither ship a bridge nor include an svc-stack consumer entry.
    """
    bridged = set(bridge_roles(root))
    return [
        role_dir.name
        for role_dir in sorted((root / "roles").iterdir())
        if role_dir.name != STACK_ROLE
        and role_dir.name not in bridged
        and _declares_stack(role_dir)
        and not any(
            STACK_ENTRY_RE.search(read_text(str(path)))
            for path in role_dir.glob("tasks/**/*.yml")
        )
    ]


def _guarded(
    node: Any, guards: tuple[str, ...]
) -> Iterator[tuple[dict, tuple[str, ...]]]:
    for task in node if isinstance(node, list) else []:
        if not isinstance(task, dict):
            continue
        when = task.get("when")
        own = guards + tuple(
            str(item).strip()
            for item in (when if isinstance(when, list) else [when])
            if item is not None and not RUN_ONCE_RE.fullmatch(str(item).strip())
        )
        yield task, own
        for key in BLOCK_KEYS:
            yield from _guarded(task.get(key), own)


def gated_core_loads(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        the bridge roles whose ``tasks/main.yml`` includes ``00_core.yml``
        under a condition besides the run-once flag, block conditions included.
    """
    return [
        role
        for role in bridge_roles(root)
        if any(
            guards
            for task, guards in _guarded(
                load_yaml_any(str(root / "roles" / role / MAIN), default_if_missing=[]),
                (),
            )
            if _task_include(task).endswith(CORE)
        )
    ]


def unadmitted_bridges(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``role: reason`` for every bridge role the loader may not run the stack
        of: one that does not declare ``stack`` literally enabled and shared,
        one the constructor enters before the loader, or one that loads its
        core under a condition besides the run-once flag.
    """
    bootstrap = bootstrap_roles(root)
    gated = set(gated_core_loads(root))
    found = []
    for role in bridge_roles(root):
        if not _declares_stack(root / "roles" / role):
            found.append(f"{role}: stack is not literally enabled and shared")
        if role in bootstrap:
            found.append(f"{role}: entered before the shared-service loader")
        if role in gated:
            found.append(f"{role}: core load gated beyond the run-once flag")
    return found


def stack_unit_facts(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``path: name`` for every fact an svc-stack task sets besides the batch
        queues, which are the only facts the stack keeps across consumers.
    """
    found = []
    for path in sorted((root / STACK_TASKS).glob("**/*.yml")):
        for task in _tasks(load_yaml_any(str(path))):
            for key in SET_FACT:
                facts = task.get(key)
                if not isinstance(facts, dict):
                    continue
                found.extend(
                    f"{path.relative_to(root)}: {name}"
                    for name in facts
                    if name not in BATCH_FACTS
                )
    return found


def _entry_files(root: Path) -> list[Path]:
    return sorted(
        [
            *root.glob("roles/*/tasks/**/*.yml"),
            *root.glob("roles/*/handlers/**/*.yml"),
            *root.glob("tasks/**/*.yml"),
            *root.glob("playbook*.yml"),
            *root.glob("playbooks/**/*.yml"),
        ]
    )


def _named_roles(mapping: dict) -> Iterator[tuple[str, bool]]:
    spec = _role_include(mapping)
    if spec:
        yield str(spec.get("name", "")), "tasks_from" in spec
    for key in ("roles", "dependencies"):
        for item in mapping.get(key) or []:
            name = item if isinstance(item, str) else None
            if isinstance(item, dict):
                name = item.get("role") or item.get("name")
            if name:
                yield str(name), False


def direct_entries(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        ``path: role`` for every full entry of a bridge role that names it
        literally, so that it bypasses the stack entry: an ``include_role`` or
        ``import_role`` without ``tasks_from``, a play's ``roles`` or a meta
        ``dependencies`` item.
    """
    bridged = set(bridge_roles(root))
    files = [*_entry_files(root), *sorted(root.glob(f"roles/*/{ROLE_FILE_META_MAIN}"))]
    found = []
    for path in files:
        for mapping in _mappings(load_yaml_any(str(path), default_if_missing=[])):
            found.extend(
                f"{path.relative_to(root)}: {name}"
                for name, partial in _named_roles(mapping)
                if name in bridged and not partial
            )
    return sorted(set(found))


def _first(tasks: list[dict], wanted: Callable[[dict], bool]) -> int:
    return next((index for index, task in enumerate(tasks) if wanted(task)), -1)


def _runs_the_entry(task: dict) -> bool:
    return ENTRY in _task_include(task) and ENTRY_GATE in str(task.get("when", ""))


def _enters_a_role(task: dict) -> bool:
    spec = _role_include(task)
    return "{{" in str(spec.get("name", "")) and "tasks_from" not in spec


def entry_sites_without_the_entry(root: Path) -> list[str]:
    """Args:
        root: the repository root.

    Returns:
        every full-role entry site of the loader that enters its role before
        it runs the stack entry gated by ``STACK_ENTRY_PENDING``.
    """
    found = []
    for site in ENTRY_SITES:
        tasks = list(_tasks(load_yaml_any(str(root / site))))
        entry, role = _first(tasks, _runs_the_entry), _first(tasks, _enters_a_role)
        if role < 0 or not 0 <= entry < role:
            found.append(str(site))
    return found


class TestStackBridge(unittest.TestCase):
    def test_every_bridge_is_the_canonical_text(self) -> None:
        offenders = non_canonical_bridges(PROJECT_ROOT)
        self.assertEqual(
            offenders,
            [],
            f"copy {CANONICAL_BRIDGE} unchanged into roles/<role>/{BRIDGE}",
        )

    def test_no_bridge_role_keeps_a_stack_entry(self) -> None:
        offenders = bridges_beside_an_entry(PROJECT_ROOT)
        self.assertEqual(
            offenders,
            [],
            "a role whose stack the loader runs includes no svc-stack consumer entry",
        )

    def test_every_stack_consumer_keeps_a_stack_path(self) -> None:
        offenders = consumers_without_a_stack_path(PROJECT_ROOT)
        self.assertEqual(
            offenders,
            [],
            f"ship {CANONICAL_BRIDGE} as roles/<role>/{BRIDGE} or include an "
            "svc-stack consumer entry",
        )

    def test_every_bridge_role_is_admitted(self) -> None:
        self.assertEqual(unadmitted_bridges(PROJECT_ROOT), [])

    def test_a_core_load_gated_beyond_the_run_once_flag_is_found(self) -> None:
        include = {"include_tasks": CORE}
        mains = {
            "gated": [{**include, "when": ["run_once_gated is not defined", "ON"]}],
            "blocked": [{"block": [include], "when": "ON"}],
            "plain": [{**include, "when": "run_once_plain is not defined"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for role, main in mains.items():
                (root / "roles" / role / BRIDGE).parent.mkdir(parents=True)
                (root / "roles" / role / BRIDGE).write_text("")
                (root / "roles" / role / MAIN).write_text(json.dumps(main))
            self.assertEqual(gated_core_loads(root), ["blocked", "gated"])

    def test_stack_units_keep_no_consumer_in_a_fact(self) -> None:
        offenders = stack_unit_facts(PROJECT_ROOT)
        self.assertEqual(
            offenders,
            [],
            "derive per-consumer values from stack_batch_consumer as loop items "
            "or include params; a fact outlives its consumer",
        )

    def test_no_file_enters_a_bridge_role_directly(self) -> None:
        offenders = direct_entries(PROJECT_ROOT)
        self.assertEqual(
            offenders,
            [],
            f"enter a bridge role through a site that runs {ENTRY} first",
        )

    def test_every_entry_site_runs_the_stack_entry_first(self) -> None:
        self.assertEqual(entry_sites_without_the_entry(PROJECT_ROOT), [])


if __name__ == "__main__":
    unittest.main()
