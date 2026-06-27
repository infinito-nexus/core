"""Flag included task files where every task repeats a hoistable directive.

When a task file is pulled in via a dynamic ``include_tasks`` and EVERY one of its
top-level tasks carries the same value for a directive that ``apply:`` can hoist
(``delegate_to``, ``become``, ``run_once``, ``notify`` ...), that value should be
set once via ``apply:`` on the include site instead of being repeated per task.

The rule is BLACKLIST-based: it flags every uniform Ansible task keyword EXCEPT
the per-task-binding ones listed in ``_IGNORED_KEYWORDS``. The task's MODULE is
never flagged: any key that is not a known Ansible task keyword (``_TASK_KEYWORDS``)
is treated as the module/action and skipped, since a module cannot be hoisted.

Per-line opt-out
================
Add ``# nocheck: include-uniform-apply-keyword`` on the first task's keyword line
(or the immediately preceding non-empty line) when the per-task setting is
deliberate.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "include-uniform-apply-keyword"

# Every recognised Ansible task keyword. A key absent from this set is the task's
# module/action (e.g. ansible.builtin.shell, uri_retry) and can never be hoisted.
_TASK_KEYWORDS = frozenset(
    {
        "action",
        "any_errors_fatal",
        "args",
        "async",
        "become",
        "become_exe",
        "become_flags",
        "become_method",
        "become_user",
        "changed_when",
        "check_mode",
        "collections",
        "connection",
        "debugger",
        "delay",
        "delegate_facts",
        "delegate_to",
        "diff",
        "environment",
        "failed_when",
        "ignore_errors",
        "ignore_unreachable",
        "local_action",
        "loop",
        "loop_control",
        "module_defaults",
        "name",
        "no_log",
        "notify",
        "poll",
        "port",
        "register",
        "remote_user",
        "retries",
        "run_once",
        "tags",
        "throttle",
        "timeout",
        "until",
        "vars",
        "when",
    }
)

# Blacklist of task keywords that must NOT be flagged even when uniform. Two
# reasons: (1) per-task binding (name/register/args/loop*/vars), block structure
# (block/rescue/always), or the include's own gate (when) are not hoistable;
# (2) LEAF-ONLY keywords (async/changed_when/delay/failed_when/poll/retries/until)
# are not valid Block attributes, and apply: wraps the included tasks in a Block,
# so it rejects them at parse ("'<kw>' is not a valid attribute for a Block").
# Only Block-valid keywords (delegate_to, run_once, become*, no_log, notify,
# tags, environment, connection, ...) can be hoisted to apply:.
_IGNORED_KEYWORDS = frozenset(
    {
        "action",
        "always",
        "args",
        "async",
        "block",
        "changed_when",
        "collections",
        "delay",
        "failed_when",
        "local_action",
        "loop",
        "loop_control",
        "module_defaults",
        "name",
        "poll",
        "register",
        "rescue",
        "retries",
        "until",
        "vars",
        "when",
    }
)

_INCLUDE_KEYS = ("include_tasks", "ansible.builtin.include_tasks")
_ROLES_LITERAL_RE = re.compile(r"roles/[^\s'\"]+\.ya?ml")
_TASKS_TAIL_RE = re.compile(r"(tasks/[^\s'\"]+\.ya?ml)\s*$")


def _is_flaggable(keyword: str) -> bool:
    return (
        keyword in _TASK_KEYWORDS
        and keyword not in _IGNORED_KEYWORDS
        and not keyword.startswith("with_")
    )


def _role_root(base_dir: Path) -> Path | None:
    for parent in [base_dir, *base_dir.parents]:
        if parent.parent.name == "roles":
            return parent
    return None


def _resolve_include(value: object, base_dir: Path) -> str | None:
    if isinstance(value, dict):
        value = value.get("file") or value.get("_raw_params")
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    literal = _ROLES_LITERAL_RE.search(v)
    if literal:
        return str((PROJECT_ROOT / literal.group(0)).resolve())
    if "{{" in v:
        tail = _TASKS_TAIL_RE.search(v)
        role_root = _role_root(base_dir)
        if tail and role_root is not None:
            return str((role_root / tail.group(1)).resolve())
        return None
    return str((base_dir / v).resolve())


def _iter_task_mappings(node: object):
    if isinstance(node, list):
        for item in node:
            yield from _iter_task_mappings(item)
    elif isinstance(node, dict):
        yield node
        for section in ("block", "rescue", "always"):
            yield from _iter_task_mappings(node.get(section))


def _mapping_items(node: yaml.MappingNode) -> dict[str, tuple[yaml.Node, int]]:
    out: dict[str, tuple[yaml.Node, int]] = {}
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode):
            out[key.value] = (value, key.start_mark.line + 1)
    return out


def _node_to_py(node: yaml.Node) -> object:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_node_to_py(child) for child in node.value]
    if isinstance(node, yaml.MappingNode):
        return {_node_to_py(k): _node_to_py(v) for k, v in node.value}
    return None


def _value_display(node: yaml.Node) -> str:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    return repr(_node_to_py(node))


class TestIncludeUniformApplyKeyword(unittest.TestCase):
    def test_uniform_keyword_should_hoist_to_apply(self) -> None:
        contents: dict[str, tuple[str, str]] = {}
        include_targets: set[str] = set()
        include_sites: dict[str, set[str]] = {}

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            abspath = str(Path(path_str).resolve())
            contents[abspath] = (rel, content)
            base_dir = Path(path_str).parent
            try:
                doc = load_yaml_any(path_str, default_if_missing=None)
            except (yaml.YAMLError, ValueError):
                continue
            for task in _iter_task_mappings(doc):
                for key in _INCLUDE_KEYS:
                    if key in task:
                        target = _resolve_include(task[key], base_dir)
                        if target:
                            include_targets.add(target)
                            include_sites.setdefault(target, set()).add(rel)

        findings: list[tuple[str, int, str, str, str]] = []
        for target in include_targets:
            entry = contents.get(target)
            if entry is None:
                continue
            rel, content = entry
            try:
                docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
            except yaml.YAMLError:
                continue
            lines = content.splitlines()
            top_items = [
                item
                for doc in docs
                if isinstance(doc, yaml.SequenceNode)
                for item in doc.value
            ]
            if len(top_items) < 2:
                continue
            if not all(isinstance(item, yaml.MappingNode) for item in top_items):
                continue

            item_maps = [_mapping_items(item) for item in top_items]
            common_keys = set(item_maps[0])
            for item_map in item_maps[1:]:
                common_keys &= set(item_map)

            sites = ", ".join(sorted(include_sites.get(target, set())))
            for keyword in sorted(k for k in common_keys if _is_flaggable(k)):
                values = {
                    repr(_node_to_py(item_map[keyword][0])) for item_map in item_maps
                }
                if len(values) != 1:
                    continue
                first_line = item_maps[0][keyword][1]
                if is_suppressed_at(lines, first_line, _RULE, mode="same-or-above"):
                    continue
                findings.append(
                    (
                        rel,
                        first_line,
                        keyword,
                        _value_display(item_maps[0][keyword][0]),
                        sites,
                    )
                )

        if findings:
            formatted = "\n".join(
                f"- {rel}:{line}: every task repeats `{kw}: {val}`"
                + (f"  (included from {sites})" if sites else "")
                for rel, line, kw, val, sites in sorted(
                    set(findings), key=lambda i: (i[0], i[1], i[2])
                )
            )
            self.fail(
                "Included task files where EVERY top-level task repeats an "
                "identical hoistable directive. For a dynamic `include_tasks`, a "
                "task keyword set via `apply:` propagates to every included task, "
                "so repeating it per task is redundant duplication.\n\n"
                "Fix one of:\n"
                "  - hoist the keyword to the include site "
                "(`include_tasks: { file: <file>, apply: { <keyword>: <value> } }`) "
                "and delete the per-task lines;\n"
                "  - if the per-task setting is intentional, add "
                "`# nocheck: include-uniform-apply-keyword` on the first task's "
                "keyword line or the line above.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
