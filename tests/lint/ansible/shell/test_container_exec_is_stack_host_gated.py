"""Enforce IS_STACK_HOST gating on ``container exec`` / ``docker exec``
calls so they never fire on swarm workers (where the resolver bails out
with exit 64).

Rationale
=========
``container_address`` (the partner lint enforces its use) resolves the
right container ID in swarm mode -- but only on a manager. On workers
the resolver script exits 64 because ``container node ls`` fails, the
``$(...)`` subshell expands to empty, and ``container exec  <cmd>``
falls over noisily. Roles must therefore gate every container-exec task
on ``when: IS_STACK_HOST | bool`` so workers skip cleanly.

Detection walks the YAML structure of each ``roles/*/tasks/*.yml`` file
and considers a container-exec line "gated" when ANY of:

* the line is inside a ``block:`` whose ``when:`` mentions
  ``IS_STACK_HOST`` (direct or via a nested parent block);
* the task itself carries ``IS_STACK_HOST`` in its ``when:``;
* the file is included from another tasks file in the same role via
  ``include_tasks: <basename>`` whose include site carries
  ``IS_STACK_HOST`` in its ``when:`` (transitive parent gate, walked
  one role-include hop deep so per-role refactors stay self-documenting).

Per-line opt-out
================
Add ``# nocheck: container-exec-stack-host-gate`` on the same line as
the ``container exec`` call OR on the immediately preceding non-empty
line. Legitimate uses include diagnostic-only tasks that already accept
the failure path on workers.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import (
    iter_project_files,
    iter_project_files_with_content,
    read_text,
)
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "container-exec-stack-host-gate"
_EXEC = re.compile(r"\b(?:container|docker)\s+exec\b")
_IS_STACK_HOST = re.compile(r"\bIS_STACK_HOST\b")
_NAME_LINE = re.compile(r"^\s*-?\s*name\s*:")
_DEFAULT_PLACEMENT_MANAGER = re.compile(
    r"^\s*default_placement\s*:\s*['\"]?manager['\"]?", re.MULTILINE
)
_INCLUDE_KEYS = frozenset(
    {
        "include_tasks",
        "ansible.builtin.include_tasks",
        "import_tasks",
        "ansible.builtin.import_tasks",
    }
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if not rel_path.endswith((".yml", ".yaml")):
        return False
    return "/tasks/" in rel_path or "/handlers/" in rel_path


def _when_carries_gate(when_value: Any) -> bool:
    if isinstance(when_value, str):
        return bool(_IS_STACK_HOST.search(when_value))
    if isinstance(when_value, list):
        return any(_when_carries_gate(v) for v in when_value)
    return False


def _mapping_to_dict(node: yaml.MappingNode) -> dict[str, yaml.Node]:
    out: dict[str, yaml.Node] = {}
    for k, v in node.value:
        if isinstance(k, yaml.ScalarNode):
            out[k.value] = v
    return out


def _when_node_carries_gate(node: yaml.Node | None) -> bool:
    if node is None:
        return False
    if isinstance(node, yaml.ScalarNode):
        return bool(_IS_STACK_HOST.search(node.value or ""))
    if isinstance(node, yaml.SequenceNode):
        return any(_when_node_carries_gate(v) for v in node.value)
    if isinstance(node, yaml.MappingNode):
        return any(_when_node_carries_gate(v) for _, v in node.value)
    return False


def _walk_for_gated_ranges(
    node: yaml.Node, parent_gated: bool, ranges: list[tuple[int, int]]
) -> None:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk_for_gated_ranges(item, parent_gated, ranges)
        return
    if not isinstance(node, yaml.MappingNode):
        return

    d = _mapping_to_dict(node)
    own_gate = _when_node_carries_gate(d.get("when"))
    local_gated = parent_gated or own_gate
    if local_gated:
        ranges.append((node.start_mark.line + 1, node.end_mark.line + 1))
    for key in ("block", "rescue", "always"):
        sub = d.get(key)
        if isinstance(sub, yaml.SequenceNode):
            _walk_for_gated_ranges(sub, local_gated, ranges)


def _collect_gated_ranges(content: str) -> list[tuple[int, int]]:
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    ranges: list[tuple[int, int]] = []
    for doc in docs:
        _walk_for_gated_ranges(doc, False, ranges)
    return ranges


def _include_target_paths(task: dict, tasks_dir: Path, parent_dir: Path) -> list[Path]:
    """Resolve the file path(s) an include task references. Handles the
    static form (``include_tasks: 04_admin.yml``), the dict form
    (``include_tasks: { file: 04_admin.yml, apply: ... }``) and the loop
    form (``include_tasks: "{{ step }}" loop: [step1.yml, step2.yml]``).

    Ansible resolves relative includes against the including file's
    directory first, then falls back to ``<role>/tasks/``."""

    def _resolve(name: str) -> Path | None:
        for base in (parent_dir, tasks_dir):
            candidate = base / name
            if candidate.is_file():
                return candidate
        return None

    targets: list[Path] = []
    for key in _INCLUDE_KEYS:
        inc = task.get(key)
        if isinstance(inc, dict):
            inc = inc.get("file")
        if not isinstance(inc, str):
            continue
        if "{{" in inc and isinstance(task.get("loop"), list):
            for item in task["loop"]:
                if isinstance(item, str) and not item.startswith("{{"):
                    resolved = _resolve(item)
                    if resolved is not None:
                        targets.append(resolved)
        elif "{{" not in inc:
            resolved = _resolve(inc)
            if resolved is not None:
                targets.append(resolved)
    return targets


def _collect_include_edges(
    tasks: Any,
    parent_gated: bool,
    parent_file: Path,
    edges: list[tuple[Path, Path, bool]],
    tasks_dir: Path,
) -> None:
    """Walk a parsed tasks list and emit (parent_file, child_file, gated)
    edges for every include encountered. `gated` accounts for both the
    include site's own ``when:`` and any enclosing block's ``when:``."""
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        own_gate = _when_carries_gate(task.get("when"))
        local_gated = parent_gated or own_gate
        edges.extend(
            (parent_file.resolve(), target.resolve(), local_gated)
            for target in _include_target_paths(task, tasks_dir, parent_file.parent)
        )
        for sub_key in ("block", "rescue", "always"):
            sub = task.get(sub_key)
            if isinstance(sub, list):
                _collect_include_edges(sub, local_gated, parent_file, edges, tasks_dir)


def _build_always_gated_files(role_dir: Path) -> set[Path]:
    """Return the set of tasks files that are ONLY ever reached through
    an include path whose chain carries an ``IS_STACK_HOST`` gate.

    Walks the role's include graph from ``main.yml`` (and any other
    file that has no parent inside the role). A file qualifies when
    every reach is gated; if even one path reaches it without a gate
    it is NOT considered always-gated and its container-exec calls
    must carry their own gate."""
    tasks_dir = role_dir / "tasks"
    if not tasks_dir.is_dir():
        return set()

    edges: list[tuple[Path, Path, bool]] = []
    all_files: set[Path] = set()
    role_rel = role_dir.relative_to(PROJECT_ROOT).as_posix() + "/tasks/"
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith(role_rel):
            continue
        try:
            data = load_yaml_any(path_str, default_if_missing=None)
        except Exception:
            continue
        yml = Path(path_str)
        all_files.add(yml.resolve())
        _collect_include_edges(data, False, yml, edges, tasks_dir)

    children_with_parent: set[Path] = {child for _, child, _ in edges}
    roots = all_files - children_with_parent

    reach: dict[Path, set[bool]] = {}

    def visit(node: Path, gated: bool) -> None:
        states = reach.setdefault(node, set())
        if gated in states:
            return
        states.add(gated)
        for parent, child, edge_gated in edges:
            if parent == node:
                visit(child, gated or edge_gated)

    for root in roots:
        visit(root, False)

    return {f for f, states in reach.items() if states == {True}}


def _role_is_manager_pinned(role_dir: Path) -> bool:
    """True when meta/services.yml declares default_placement: manager.
    Such roles are auto-placed by the constructor on the swarm manager
    only -- workers never load them, so IS_STACK_HOST gating would be
    redundant noise."""
    services_yml = role_dir / ROLE_FILE_META_SERVICES
    if not services_yml.is_file():
        return False
    try:
        text = read_text(str(services_yml))
    except OSError:
        return False
    return bool(_DEFAULT_PLACEMENT_MANAGER.search(text))


class TestContainerExecStackHostGate(unittest.TestCase):
    def test_container_exec_must_be_is_stack_host_gated(self) -> None:
        findings: list[tuple[str, int, str]] = []
        role_include_cache: dict[Path, set[Path]] = {}
        role_manager_pinned_cache: dict[Path, bool] = {}

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            parts = rel.split("/")
            role_dir = PROJECT_ROOT / parts[0] / parts[1]
            if role_dir not in role_manager_pinned_cache:
                role_manager_pinned_cache[role_dir] = _role_is_manager_pinned(role_dir)
            if role_manager_pinned_cache[role_dir]:
                continue
            if role_dir not in role_include_cache:
                role_include_cache[role_dir] = _build_always_gated_files(role_dir)
            file_gated = Path(path_str).resolve() in role_include_cache[role_dir]

            gated_ranges = _collect_gated_ranges(content)
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _EXEC.search(line):
                    continue
                if _NAME_LINE.match(line):
                    continue
                line_no = idx + 1
                if file_gated or any(s <= line_no <= e for s, e in gated_ranges):
                    continue
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {snip}"
                for p, ln, snip in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                "Found `container exec` / `docker exec` tasks NOT gated on "
                "`IS_STACK_HOST | bool`. In swarm mode the helper exits 64 "
                "on workers and the exec call fails noisily.\n\n"
                "Fix one of:\n"
                "  - wrap the task(s) in a block with "
                "`when: IS_STACK_HOST | bool`;\n"
                "  - add `when: IS_STACK_HOST | bool` directly on the task;\n"
                "  - include the file from another tasks file via "
                "`include_tasks: ...` whose include carries that gate;\n"
                "  - or, for diagnostic-only paths that should attempt on "
                "workers anyway, add `# nocheck: container-exec-stack-host"
                "-gate` on the same line or the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
