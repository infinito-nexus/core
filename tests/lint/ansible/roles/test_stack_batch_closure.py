from __future__ import annotations

import os
import re
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_TASKS_MAIN

from . import PROJECT_ROOT
from .test_stack_bridge import BATCH_FACTS, ROLE_INCLUDES, TASK_INCLUDES

if TYPE_CHECKING:
    from collections.abc import Iterator

STACK_ROLE = "svc-stack"
P1_SEED = Path("roles/svc-stack/tasks/batch/warm.yml")
P2_SEED = Path("roles/svc-stack/tasks/batch/front.yml")
ONCE_FLAG = "utils/once/flag.yml"
META = ("meta", "ansible.builtin.meta")
SET_FACT = ("set_fact", "ansible.builtin.set_fact")
PATH_ABSOLUTE = re.compile(r"lookup\(\s*'path_absolute'\s*,\s*'([^']+)'\s*\)")
PLAIN = re.compile(r"^\{\{\s*(\w+)\s*(\|\s*first\s*)?\}\}$")
ONCE_GUARD = re.compile(
    r"run_once_(\w+) is not defined|not \(run_once_(\w+) \| default\(false\) \| bool\)"
)
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
EXPRESSION_KEYS = ("when", "that", "until", "changed_when", "failed_when")
READER_DIRS = ("tasks", "templates", "vars", "defaults", "meta")
CONSUMER_VARS = re.compile(
    r"\b(application_id|domain|stack_batch_consumer|stack_batch_item)\b"
)
FALSE_IN_BATCH = frozenset(
    {
        "stack_front_phase == 'entered'",
        "not (service_loader_preloading | default(false) | bool)",
        "not (stack_batch_running | bool)",
    }
)
EXPANSIONS: dict[tuple[str, str], tuple[str, ...]] = {
    (
        f"roles/sys-svc-certs/{ROLE_FILE_TASKS_MAIN}",
        "{{ [role_path, 'tasks/flavors', CERTBOT_FLAVOR ~'.yml'] | path_join }}",
    ): ("roles/sys-svc-certs/tasks/flavors/*.yml",),
    (
        "roles/sys-ctl-alm-compose/tasks/00_core.yml",
        "{{ sys_ctl_alm_compose_dependency }}",
    ): ("sys-ctl-alm-email", "sys-ctl-alm-telegram"),
}
ACCUMULATORS = frozenset(
    {
        *BATCH_FACTS,
        "webserver_csp_hashes_extra_by_vhost",
        "service_loader_post_run",
        "system_service_run_list",
        "system_service_run_once_list",
        "cf_zones_to_purge",
    }
)


@dataclass
class Closure:
    files: set[Path] = field(default_factory=set)
    flags: set[str] = field(default_factory=set)
    flushes: set[str] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)


def _conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [str(item).strip() for item in (when if isinstance(when, list) else [when])]


def _tasks(
    node: Any, inherited: tuple[str, ...] = ()
) -> Iterator[tuple[dict, tuple[str, ...]]]:
    for task in node if isinstance(node, list) else []:
        if not isinstance(task, dict):
            continue
        conditions = (*inherited, *_conditions(task))
        yield task, conditions
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key), conditions)


def _bindings(task: dict, context: dict) -> list[dict]:
    vars_ = task.get("vars") if isinstance(task.get("vars"), dict) else {}
    scope = {
        **context,
        **{k: v for k, v in vars_.items() if isinstance(v, (str, list))},
    }
    loop = task.get("loop")
    if not isinstance(loop, list):
        return [scope]
    loop_var = (task.get("loop_control") or {}).get("loop_var", "item")
    return [{**scope, loop_var: str(item)} for item in loop]


def _resolve(ref: str, scope: dict, source: str, role: str | None) -> list[str] | None:
    ref = ref.replace("{{ role_path }}", f"roles/{role}")
    match = PATH_ABSOLUTE.search(ref)
    if match:
        return [match.group(1)]
    if "{{" not in ref:
        return [ref]
    if (source, ref) in EXPANSIONS:
        expanded: list[str] = []
        for pattern in EXPANSIONS[(source, ref)]:
            expanded += (
                [
                    str(p.relative_to(PROJECT_ROOT))
                    for p in sorted(PROJECT_ROOT.glob(pattern))
                ]
                if "*" in pattern
                else [pattern]
            )
        return expanded
    plain = PLAIN.match(ref.strip())
    if not plain or plain.group(1) not in scope:
        return None
    value = scope[plain.group(1)]
    if isinstance(value, list):
        return [str(value[0])] if plain.group(2) else [str(item) for item in value]
    return _resolve(str(value), scope, source, role)


def _task_file(current: Path, role: str | None, ref: str) -> Path | None:
    candidates = [PROJECT_ROOT / ref] if ref.startswith(("roles/", "tasks/")) else []
    candidates.append(current.parent / ref)
    if role:
        candidates.append(PROJECT_ROOT / "roles" / role / "tasks" / ref)
    candidates += [PROJECT_ROOT / "tasks" / ref, PROJECT_ROOT / ref]
    return next((path.resolve() for path in candidates if path.is_file()), None)


def _role_entries(name: str, tasks_from: str) -> list[tuple[Path, str]]:
    entry = (
        tasks_from if tasks_from.endswith((".yml", ".yaml")) else f"{tasks_from}.yml"
    )
    entries = [((PROJECT_ROOT / "roles" / name / "tasks" / entry).resolve(), name)]
    meta = load_yaml_any(
        str(PROJECT_ROOT / "roles" / name / ROLE_FILE_META_MAIN), default_if_missing={}
    )
    for dep in (meta or {}).get("dependencies") or []:
        dep_name = dep if isinstance(dep, str) else dep.get("role") or dep.get("name")
        entries.append(
            (
                (PROJECT_ROOT / "roles" / dep_name / ROLE_FILE_TASKS_MAIN).resolve(),
                dep_name,
            )
        )
    return entries


def walk(seed: Path, prune_flags: frozenset[str] = frozenset()) -> Closure:
    """Args:
        seed: the task file of svc-stack the walk starts from.
        prune_flags: run-once flags already set when the seed runs; an include
            guarded by one of them is not followed.

    Returns:
        the closure of every include the seed reaches in the front batch,
        where the conditions of FALSE_IN_BATCH never hold.
    """
    closure = Closure()
    stack: list[tuple[Path, str | None, tuple]] = [
        ((PROJECT_ROOT / seed).resolve(), STACK_ROLE, ())
    ]
    seen: set[tuple] = set()
    while stack:
        path, role, frozen = stack.pop()
        if (path, role, frozen) in seen or not path.is_file():
            continue
        seen.add((path, role, frozen))
        closure.files.add(path)
        context = dict(frozen)
        source = str(path.relative_to(PROJECT_ROOT))
        for task, conditions in _tasks(load_yaml_any(str(path), default_if_missing=[])):
            guards = {
                flag
                for c in conditions
                for pair in ONCE_GUARD.findall(c)
                for flag in pair
                if flag
            }
            if FALSE_IN_BATCH.intersection(conditions) or guards & prune_flags:
                continue
            if any(task.get(key) == "flush_handlers" for key in META):
                closure.flushes.add(source)
            for scope in _bindings(task, context):
                child = tuple(
                    sorted(
                        (k, tuple(v) if isinstance(v, list) else v)
                        for k, v in scope.items()
                    )
                )
                for key in TASK_INCLUDES:
                    spec = task.get(key)
                    ref = spec.get("file") if isinstance(spec, dict) else spec
                    if not isinstance(ref, str):
                        continue
                    if ref.endswith(ONCE_FLAG) and role:
                        closure.flags.add(role.replace("-", "_"))
                    for target in _resolve(ref, scope, source, role) or [None]:
                        found = _task_file(path, role, target) if target else None
                        if found is None:
                            closure.unresolved.add(f"{source}: include_tasks {ref}")
                        else:
                            stack.append((found, role, child))
                for key in ROLE_INCLUDES:
                    spec = task.get(key)
                    if not isinstance(spec, dict):
                        continue
                    names = _resolve(str(spec.get("name", "")), scope, source, role)
                    tasks_from = _resolve(
                        str(spec.get("tasks_from", "main.yml")), scope, source, role
                    )
                    if names is None or tasks_from is None:
                        closure.unresolved.add(
                            f"{source}: include_role {spec.get('name')}"
                        )
                        continue
                    for name in names:
                        stack.extend(
                            (entry, owner, child)
                            for entry, owner in _role_entries(name, tasks_from[0])
                        )
    return closure


def _expressions(path: Path) -> str:
    text = read_text(str(path))
    if path.suffix not in (".yml", ".yaml"):
        return " ".join(JINJA.findall(text))
    found = []

    def collect(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                collect(value, str(name))
        elif isinstance(node, list):
            for value in node:
                collect(value, key)
        elif isinstance(node, str):
            found.append(
                node if key in EXPRESSION_KEYS else " ".join(JINJA.findall(node))
            )

    collect(load_yaml_any(str(path), default_if_missing={}))
    return " ".join(found)


def _sets(path: Path) -> set[str]:
    names: set[str] = set()
    for task, _ in _tasks(load_yaml_any(str(path), default_if_missing=[])):
        for key in SET_FACT:
            if isinstance(task.get(key), dict):
                names.update(
                    str(n) for n in task[key] if "{{" not in str(n) and n != "cacheable"
                )
        if isinstance(task.get("register"), str):
            names.add(task["register"])
    return names


def outside_readers(closure: Closure) -> list[str]:
    """Args:
        closure: the P2 closure.

    Returns:
        ``name: reader`` for every name a P2 task sets that a file outside
        the closure reads: a task file of any role, or a template, vars,
        defaults or meta file of a role the closure does not enter. A reader
        that sets the name itself and the declared accumulators are exempt.
    """
    set_in = set().union(*(_sets(path) for path in closure.files)) - ACCUMULATORS
    if not set_in:
        return []
    names = re.compile(r"\b(" + "|".join(map(re.escape, sorted(set_in))) + r")\b")
    entered = {
        path.relative_to(PROJECT_ROOT).parts[1]
        for path in closure.files
        if path.is_relative_to(PROJECT_ROOT / "roles")
    }
    found = []
    roles = f"{PROJECT_ROOT / 'roles'}{os.sep}"
    for path in sorted(
        Path(path)
        for path in iter_project_files(extensions=(".yml", ".yaml", ".j2"))
        if path.startswith(roles)
    ):
        parts = path.relative_to(PROJECT_ROOT).parts
        if path.resolve() in closure.files or len(parts) < 4:
            continue
        if parts[2] not in READER_DIRS or (parts[1] in entered and parts[2] != "tasks"):
            continue
        own = _sets(path) if parts[2] == "tasks" else set()
        found.extend(
            f"{name}: {path.relative_to(PROJECT_ROOT)}"
            for name in sorted(set(names.findall(_expressions(path))) - own)
        )
    return found


def consumer_reads(path: Path) -> list[str]:
    """Args:
        path: a once-entry of the warm-up.

    Returns:
        the consumer variables its expressions read.
    """
    return sorted(set(CONSUMER_VARS.findall(_expressions(path))))


class TestStackBatchClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.p1 = walk(P1_SEED)
        cls.p2 = walk(P2_SEED, frozenset({*cls.p1.flags, STACK_ROLE.replace("-", "_")}))

    def test_every_templated_include_of_the_batch_resolves(self) -> None:
        self.assertEqual(
            sorted(self.p1.unresolved | self.p2.unresolved),
            [],
            "resolve the include through the include vars or add it to EXPANSIONS",
        )

    def test_no_flush_is_reachable_from_the_fronts(self) -> None:
        self.assertEqual(
            sorted(self.p2.flushes),
            [],
            "a flush reachable from P2 reloads OpenResty mid-batch; guard it "
            "behind a run-once flag that the warm-up in batch/warm.yml sets",
        )

    def test_the_warm_up_once_entries_read_no_consumer_variable(self) -> None:
        entries = {
            f"{spec['name']}/{spec['tasks_from']}": consumer_reads(
                PROJECT_ROOT / "roles" / spec["name"] / "tasks" / spec["tasks_from"]
            )
            for task, _ in _tasks(load_yaml_any(str(PROJECT_ROOT / P1_SEED)))
            for spec in [next((task[k] for k in ROLE_INCLUDES if k in task), {})]
            if "tasks_from" in spec
        }
        self.assertTrue(entries)
        self.assertEqual(
            {entry: reads for entry, reads in entries.items() if reads}, {}
        )

    def test_no_name_a_front_sets_is_read_outside_the_fronts(self) -> None:
        self.assertEqual(
            outside_readers(self.p2),
            [],
            "a body reading it after P2 gets the last consumer's value; "
            "derive it from a lookup keyed by application_id instead",
        )

    def test_every_expansion_still_names_a_live_include(self) -> None:  # nocheck: test.text-presence -- staleness guard of the lint's own expansion table  # fmt: skip
        stale = [
            f"{source}: {ref}"
            for source, ref in EXPANSIONS
            if ref not in read_text(str(PROJECT_ROOT / source))
        ]
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
