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
  one role-include hop deep so per-role refactors stay self-documenting);
* the line is inside the command of a ``shell``/``command`` task that runs
  once (``run_once: true`` on the task, on an enclosing block, or in the
  ``apply:`` of every include chain that reaches the file) on
  ``{{ <PREFIX>_HOST_NODE }}`` (its own ``delegate_to``, else the nearest
  enclosing block's), whose every exec enters ``{{ <PREFIX>_LOCAL_CID }}``
  (at most piped through ``quote``, ``trim`` or ``string``) as its container
  operand, and ahead of which an include of
  ``{{ lookup('path_absolute', 'roles/sys-svc-compose/tasks/utils/swarm/resolve_host_cid.yml') }}``
  with the literal ``resolve_output_prefix: <PREFIX>`` has run on every
  path. Such a task executes exactly once, on the node hosting the service,
  against the container id the resolver read there, so no manager-only
  ``container_address`` subshell is involved. The include counts when it
  runs unconditionally ahead of the task: earlier in the same task list or
  in the ``block:`` of an enclosing or earlier block without ``when:`` or
  ``rescue:``, never from a ``rescue:``/``always:`` section, never with its
  own ``when:``, loop, ``ignore_errors`` or ``never`` tag or an ``apply:``
  that adds one of them or ``vars:``, either in the file itself or, on every
  include chain of the role that reaches the file, ahead of the include that
  leads on. A ``set_fact``/``register`` of ``<PREFIX>_LOCAL_CID`` or
  ``<PREFIX>_HOST_NODE`` after it, or ``vars:`` naming one on the task or a
  block around it, cancels it. A file entered from outside its role's
  include graph (a ``path_absolute`` include or ``include_role``'s
  ``tasks_from``) starts with no prefix set.

Per-line opt-out
================
Add ``# nocheck: container-exec-stack-host-gate`` on the same line as
the ``container exec`` call OR on the immediately preceding non-empty
line. Legitimate uses include diagnostic-only tasks that already accept
the failure path on workers.
"""

from __future__ import annotations

import re
import shlex
import tempfile
import unittest
from collections.abc import Callable, Iterable, Iterator
from functools import cache
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
_ROLE_PATH_TASKS = re.compile(r"^\{\{\s*role_path\s*\}\}/tasks/")
_DEFAULT_PLACEMENT_MANAGER = re.compile(
    r"^\s*placement\s*:\s*['\"]?manager['\"]?", re.MULTILINE
)
_INCLUDE_KEYS = frozenset(
    {
        "include_tasks",
        "ansible.builtin.include_tasks",
        "import_tasks",
        "ansible.builtin.import_tasks",
    }
)
_RESOLVE_HOST_CID = "roles/sys-svc-compose/tasks/utils/swarm/resolve_host_cid.yml"
_RESOLVER_INCLUDE = re.compile(
    r"\s*\{\{\s*lookup\(\s*(['\"])path_absolute\1\s*,\s*(['\"])"
    + re.escape(_RESOLVE_HOST_CID)
    + r"\2\s*\)\s*\}\}\s*"
)
_RESOLVED_FACT = re.compile(r"^(\w+)_(?:LOCAL_CID|HOST_NODE)$")
_SET_FACT_KEYS = ("set_fact", "ansible.builtin.set_fact")
_HOST_NODE_DELEGATE = re.compile(r"^\s*\{\{\s*(\w+)_HOST_NODE\s*\}\}\s*$")
_ITERATION_KEY = re.compile(r"^(?:loop|with_\w+)$")
_COMMAND_MODULES = (
    "ansible.builtin.shell",
    "shell",
    "ansible.builtin.command",
    "command",
)
_ROLE_INCLUDE_KEYS = frozenset(
    {
        "include_role",
        "ansible.builtin.include_role",
        "import_role",
        "ansible.builtin.import_role",
    }
)
_PATH_ABSOLUTE_TASKS = re.compile(
    r"lookup\(\s*['\"]path_absolute['\"]\s*,\s*"
    r"['\"](roles/[^'\"]+/tasks/[^'\"]+\.ya?ml)['\"]"
)
_JINJA_EXPRESSION = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_HIDDEN_EXPRESSION = re.compile(r"@@(\d+)@@")
_EXEC_VALUE_OPTIONS = frozenset(
    {"-e", "--env", "--env-file", "-u", "--user", "-w", "--workdir", "--detach-keys"}
)
_TRUE = frozenset({"true", "yes", "on"})
_RUN_ONCE = yaml.ScalarNode(tag="tag:yaml.org,2002:bool", value="true")


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
    form (``include_tasks: "{{ step }}" loop: [step1.yml, step2.yml]``) and
    the ``{{ role_path }}/tasks/...`` form, which a file reached through
    ``tasks_from`` must use because the relative form resolves against a
    different base there.

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
        inc = _ROLE_PATH_TASKS.sub("", inc)
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


def _role_task_paths(role_dir: Path) -> Iterator[str]:
    role_rel = role_dir.relative_to(PROJECT_ROOT).as_posix() + "/tasks/"
    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        if Path(path_str).relative_to(PROJECT_ROOT).as_posix().startswith(role_rel):
            yield path_str


@cache
def _role_task_files(role_dir: Path) -> tuple[tuple[Path, Any], ...]:
    """Parse every tasks file of one role.

    Args:
      role_dir: the role's directory.

    Returns:
      ``(path, parsed content)`` of each YAML file under the role's
      ``tasks/``; a file that does not parse is left out.
    """
    files: list[tuple[Path, Any]] = []
    for path_str in _role_task_paths(role_dir):
        try:
            data = load_yaml_any(path_str, default_if_missing=None)
        except Exception:
            continue
        files.append((Path(path_str), data))
    return tuple(files)


@cache
def _role_task_docs(role_dir: Path) -> tuple[tuple[Path, yaml.Node], ...]:
    """Compose every tasks file of one role.

    Args:
      role_dir: the role's directory.

    Returns:
      ``(path, first composed document)`` of each YAML file under the role's
      ``tasks/``; a file that does not compose is left out.
    """
    docs: list[tuple[Path, yaml.Node]] = []
    for path_str in _role_task_paths(role_dir):
        try:
            composed = list(
                yaml.compose_all(read_text(path_str), Loader=yaml.SafeLoader)
            )
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        doc = next((d for d in composed if d is not None), None)
        if doc is not None:
            docs.append((Path(path_str), doc))
    return tuple(docs)


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
    for yml, data in _role_task_files(role_dir):
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


def _plain(node: yaml.Node | None) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_plain(item) for item in node.value]
    if isinstance(node, yaml.MappingNode):
        return {key: _plain(value) for key, value in _mapping_to_dict(node).items()}
    return None


def _is_true(value: Any) -> bool:
    if isinstance(value, yaml.ScalarNode):
        value = value.value
    return isinstance(value, str) and value.lower() in _TRUE


def _tags(value: Any) -> set[str]:
    if isinstance(value, str):
        return {tag.strip() for tag in value.split(",")}
    if isinstance(value, list):
        return {str(tag).strip() for tag in value}
    return set()


def _may_skip(keywords: dict[str, Any]) -> bool:
    return (
        "when" in keywords
        or any(_ITERATION_KEY.match(key) for key in keywords)
        or _is_true(keywords.get("ignore_errors"))
        or "never" in _tags(keywords.get("tags"))
    )


def _unconditional(task: dict[str, Any]) -> bool:
    """Tell whether a task or block runs whenever the list it sits in runs.

    Args:
      task: the plain mapping of one task or block.

    Returns:
      False when it carries ``when:``, a loop, ``ignore_errors`` or the
      ``never`` tag, or includes a file with an ``apply:`` that does or that
      sets ``vars:``.
    """
    if _may_skip(task):
        return False
    for key in _INCLUDE_KEYS:
        spec = task.get(key)
        apply = spec.get("apply") if isinstance(spec, dict) else None
        if isinstance(apply, dict) and (_may_skip(apply) or "vars" in apply):
            return False
    return True


def _resolver_prefix(task: dict) -> str | None:
    """Read the prefix a resolve_host_cid.yml include sets its facts under.

    Args:
      task: one parsed task.

    Returns:
      The literal ``resolve_output_prefix`` when the task includes exactly
      resolve_host_cid.yml through ``lookup('path_absolute', …)``, otherwise
      None; a templated prefix is None too.
    """
    for key in _INCLUDE_KEYS:
        inc = task.get(key)
        if isinstance(inc, dict):
            inc = inc.get("file")
        if not isinstance(inc, str) or not _RESOLVER_INCLUDE.fullmatch(inc):
            continue
        task_vars = task.get("vars")
        if not isinstance(task_vars, dict):
            continue
        prefix = task_vars.get("resolve_output_prefix")
        if isinstance(prefix, str) and "{{" not in prefix:
            return prefix
    return None


_TaskVisitor = Callable[
    [yaml.MappingNode, dict[str, Any], frozenset[str], dict[str, yaml.Node]], None
]


def _ignore_task(
    node: yaml.MappingNode,
    task: dict[str, Any],
    before: frozenset[str],
    keywords: dict[str, yaml.Node],
) -> None:
    return None


def _walk(
    seq: yaml.Node | None,
    before: frozenset[str],
    keywords: dict[str, yaml.Node],
    visit: _TaskVisitor,
    gain: Callable[[dict[str, Any]], frozenset[str]],
) -> frozenset[str]:
    """Walk a task list in run order, tracking the resolver prefixes set.

    Args:
      seq: a composed task list.
      before: the resolver prefixes set before the list runs.
      keywords: the ``delegate_to``/``run_once`` nodes the enclosing blocks
        set.
      visit: called with each task's node, its plain mapping, the prefixes
        set before it and the ``delegate_to``/``run_once`` in force for it.
      gain: the prefixes a task sets for every task after it.

    Returns:
      The prefixes set once the list has run. Only an unconditional task,
      or the ``block:`` of an unconditional block without ``rescue:``, adds
      any; ``rescue:`` and ``always:`` sections never do. A task or block
      that sets ``<prefix>_LOCAL_CID`` or ``<prefix>_HOST_NODE`` itself, by
      ``set_fact``, ``register`` or ``vars:``, drops the prefix.
    """
    if not isinstance(seq, yaml.SequenceNode):
        return before
    current = before
    for item in seq.value:
        if not isinstance(item, yaml.MappingNode):
            continue
        nodes = _mapping_to_dict(item)
        scoped = {
            **keywords,
            **{key: nodes[key] for key in ("delegate_to", "run_once") if key in nodes},
        }
        if "block" in nodes:
            block = {
                key: _plain(value)
                for key, value in nodes.items()
                if key not in ("block", "rescue", "always")
            }
            inner = current - _overwritten(block, ("vars",))
            after = _walk(nodes["block"], inner, scoped, visit, gain)
            for key in ("rescue", "always"):
                _walk(nodes.get(key), inner, scoped, visit, gain)
            if _unconditional(block) and "rescue" not in nodes:
                current = after
            continue
        task = _plain(item)
        visit(item, task, current, scoped)
        current = current - _overwritten(task, (*_SET_FACT_KEYS, "register"))
        if _unconditional(task):
            current = current | gain(task)
    return current


def _overwritten(task: dict[str, Any], keys: tuple[str, ...]) -> frozenset[str]:
    """Return the resolver prefixes whose facts a task or block sets itself.

    Args:
      task: the plain mapping of one task or block.
      keys: the keywords to read: ``set_fact`` and ``register`` for what
        outlives the task, ``vars`` for what holds inside it.

    Returns:
      Every ``<prefix>`` of a ``<prefix>_LOCAL_CID``/``<prefix>_HOST_NODE``
      those keywords name.
    """
    names: list[str] = []
    for key in keys:
        value = task.get(key)
        if isinstance(value, dict):
            names.extend(value)
        elif isinstance(value, str):
            names.append(value)
    return frozenset(
        match.group(1) for name in names if (match := _RESOLVED_FACT.match(name))
    )


def _command_text(task: dict[str, Any]) -> str | None:
    for key in _COMMAND_MODULES:
        body = task.get(key)
        if isinstance(body, dict):
            body = body.get("cmd", body.get("argv"))
        if isinstance(body, list):
            body = " ".join(str(item) for item in body)
        if isinstance(body, str):
            return body
    return None


def _shell_words(text: str) -> Iterator[str]:
    lexer = shlex.shlex(text, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        for word in lexer:
            if word.strip():
                yield word.strip()
    except ValueError:
        return


def _exec_operand(tokens: Iterable[str]) -> str | None:
    skip = False
    for token in tokens:
        if skip:
            skip = False
        elif token in _EXEC_VALUE_OPTIONS:
            skip = True
        elif not token.startswith("-"):
            return token
    return None


def _execs_enter(command: str, local_cid: str) -> bool:
    """Tell whether every exec of a command enters one given container.

    Args:
      command: the ``shell``/``command`` text of one task.
      local_cid: the var whose value the container operand must be.

    Returns:
      True when the command runs at least one exec, none of them inside a
      Jinja expression, and the first operand after each exec's options is
      ``{{ <local_cid> }}``, at most piped through ``quote``, ``trim`` or
      ``string``.
    """
    expressions: list[str] = []

    def hide(match: re.Match[str]) -> str:
        expressions.append(match.group(1))
        return f"@@{len(expressions) - 1}@@"

    hidden = _JINJA_EXPRESSION.sub(hide, command)
    matches = list(_EXEC.finditer(hidden))
    if not matches or len(matches) != len(_EXEC.findall(command)):
        return False
    names_cid = re.compile(
        rf"\s*{re.escape(local_cid)}\s*(?:\|\s*(?:quote|trim|string)\s*)*"
    )
    for match in matches:
        operand = _exec_operand(_shell_words(hidden[match.end() :]))
        found = _HIDDEN_EXPRESSION.fullmatch(operand or "")
        if found is None or not names_cid.fullmatch(expressions[int(found.group(1))]):
            return False
    return True


def _runs_once_on_host_node(
    task: dict[str, Any], before: frozenset[str], keywords: dict[str, yaml.Node]
) -> bool:
    """Tell whether a task runs once on a resolved host node's local container.

    Args:
      task: the plain mapping of one task.
      before: the resolver prefixes set before the task runs.
      keywords: the ``delegate_to``/``run_once`` nodes in force for the task.

    Returns:
      True when ``delegate_to`` is ``{{ <prefix>_HOST_NODE }}`` for a prefix
      in ``before``, ``run_once`` is true and every exec of the task's
      ``shell``/``command`` enters ``{{ <prefix>_LOCAL_CID }}``.
    """
    delegate = keywords.get("delegate_to")
    run_once = keywords.get("run_once")
    if not isinstance(delegate, yaml.ScalarNode) or not isinstance(
        run_once, yaml.ScalarNode
    ):
        return False
    match = _HOST_NODE_DELEGATE.match(delegate.value or "")
    if match is None or match.group(1) not in before:
        return False
    if match.group(1) in _overwritten(task, ("vars",)) or not _is_true(run_once):
        return False
    command = _command_text(task)
    return command is not None and _execs_enter(command, f"{match.group(1)}_LOCAL_CID")


def _command_node(node: yaml.MappingNode) -> yaml.Node | None:
    nodes = _mapping_to_dict(node)
    for key in _COMMAND_MODULES:
        body = nodes.get(key)
        if isinstance(body, yaml.MappingNode):
            args = _mapping_to_dict(body)
            body = args.get("cmd", args.get("argv"))
        if body is not None:
            return body
    return None


def _last_line(node: yaml.Node) -> int:
    if isinstance(node, yaml.MappingNode) and node.value:
        return _last_line(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and node.value:
        return _last_line(node.value[-1])
    end = node.end_mark
    if end.column == 0 and end.line > node.start_mark.line:
        return end.line
    return end.line + 1


class _ResolverGraph:
    """The resolver prefixes set ahead of every task of one role.

    Args:
      docs: ``(path, composed document)`` of every tasks file of the role.
      tasks_dir: the role's ``tasks/`` directory.
      entered: tasks files a file outside the role's include graph enters,
        which start with no prefix set.
    """

    def __init__(
        self,
        docs: tuple[tuple[Path, yaml.Node], ...],
        tasks_dir: Path,
        entered: frozenset[Path],
    ) -> None:
        self._docs = {path.resolve(): doc for path, doc in docs}
        self._tasks_dir = tasks_dir
        self._produced: dict[Path, frozenset[str]] = {}
        self._inherited = self._inherit({path.resolve() for path in entered})

    def _targets(self, path: Path, task: dict[str, Any]) -> list[Path]:
        return [
            target.resolve()
            for target in _include_target_paths(task, self._tasks_dir, path.parent)
        ]

    def _gain(self, path: Path) -> Callable[[dict[str, Any]], frozenset[str]]:
        def gain(task: dict[str, Any]) -> frozenset[str]:
            prefix = _resolver_prefix(task)
            if prefix is not None:
                return frozenset({prefix})
            return frozenset().union(
                *(self._produces(target) for target in self._targets(path, task))
            )

        return gain

    def _produces(self, path: Path) -> frozenset[str]:
        if path not in self._produced:
            self._produced[path] = frozenset()
            self._produced[path] = _walk(
                self._docs.get(path), frozenset(), {}, _ignore_task, self._gain(path)
            )
        return self._produced[path]

    def _sites(self, path: Path) -> list[tuple[Path, frozenset[str], bool]]:
        sites: list[tuple[Path, frozenset[str], bool]] = []

        def visit(
            node: yaml.MappingNode,
            task: dict[str, Any],
            before: frozenset[str],
            keywords: dict[str, yaml.Node],
        ) -> None:
            once = _is_true(keywords.get("run_once")) or any(
                isinstance(spec := task.get(key), dict)
                and isinstance(spec.get("apply"), dict)
                and _is_true(spec["apply"].get("run_once"))
                for key in _INCLUDE_KEYS
            )
            sites.extend((child, before, once) for child in self._targets(path, task))

        _walk(self._docs[path], frozenset(), {}, visit, self._gain(path))
        return sites

    def _inherit(self, entered: set[Path]) -> dict[Path, tuple[frozenset[str], bool]]:
        edges = {path: self._sites(path) for path in self._docs}
        children = {child for sites in edges.values() for child, _, _ in sites}
        reach: dict[Path, set[tuple[frozenset[str], bool]]] = {}

        def enter(node: Path, inherited: frozenset[str], once: bool) -> None:
            states = reach.setdefault(node, set())
            if (inherited, once) in states:
                return
            states.add((inherited, once))
            for child, before, site_once in edges.get(node, []):
                enter(child, inherited | before, once or site_once)

        for path in self._docs:
            if path not in children or path in entered:
                enter(path, frozenset(), False)
        return {
            path: (
                frozenset.intersection(*(prefixes for prefixes, _ in reach[path])),
                all(once for _, once in reach[path]),
            )
            if reach.get(path)
            else (frozenset(), False)
            for path in self._docs
        }

    def gated_ranges(self, path: Path) -> list[tuple[int, int]]:
        """Return the line ranges of the tasks the host-node form gates.

        Args:
          path: one tasks file of the role.

        Returns:
          1-based inclusive ``(first, last)`` line range of the command of
          every task of the file that ``_runs_once_on_host_node`` accepts.
        """
        resolved = path.resolve()
        ranges: list[tuple[int, int]] = []

        def visit(
            node: yaml.MappingNode,
            task: dict[str, Any],
            before: frozenset[str],
            keywords: dict[str, yaml.Node],
        ) -> None:
            command = _command_node(node)
            if command is not None and _runs_once_on_host_node(task, before, keywords):
                ranges.append((command.start_mark.line + 1, _last_line(command)))

        prefixes, once = self._inherited.get(resolved, (frozenset(), False))
        _walk(
            self._docs.get(resolved),
            prefixes,
            {"run_once": _RUN_ONCE} if once else {},
            visit,
            self._gain(resolved),
        )
        return ranges


def _mappings(data: Any) -> Iterator[dict]:
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _mappings(value)
    elif isinstance(data, list):
        for item in data:
            yield from _mappings(item)


def _tasks_entered_by(content: str) -> set[Path]:
    """Find the tasks files one YAML file enters from outside their include graph.

    Args:
      content: text of one YAML file.

    Returns:
      Absolute path of every ``roles/<role>/tasks/…`` file the content
      includes through ``lookup('path_absolute', …)`` or names as
      ``include_role``/``import_role`` ``tasks_from``.
    """
    entered = {
        (PROJECT_ROOT / rel).resolve() for rel in _PATH_ABSOLUTE_TASKS.findall(content)
    }
    if "tasks_from" not in content:
        return entered
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return entered
    for mapping in _mappings([_plain(doc) for doc in docs]):
        for key in _ROLE_INCLUDE_KEYS:
            spec = mapping.get(key)
            if not isinstance(spec, dict):
                continue
            role, name = spec.get("name"), spec.get("tasks_from")
            if not isinstance(role, str) or not isinstance(name, str) or "{{" in role:
                continue
            if not name.endswith((".yml", ".yaml")):
                name += ".yml"
            entered.add((PROJECT_ROOT / "roles" / role / "tasks" / name).resolve())
    return entered


@cache
def _entered_from_outside() -> frozenset[Path]:
    entered: set[Path] = set()
    for _, content in iter_project_files_with_content(extensions=(".yml", ".yaml")):
        entered |= _tasks_entered_by(content)
    return frozenset(entered)


def _role_is_manager_pinned(role_dir: Path) -> bool:
    """True when meta/services.yml declares placement: manager.
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


def _resolve_include(prefix: str, extra: str = "") -> str:
    return (
        "- ansible.builtin.include_tasks: "
        f"\"{{{{ lookup('path_absolute', '{_RESOLVE_HOST_CID}') }}}}\"\n"
        "  vars:\n"
        f"    resolve_output_prefix: {prefix}\n"
        f"{extra}"
    )


def _exec_task(
    delegate: str,
    container: str = "APP_LOCAL_CID | quote",
    tail: str = "  run_once: true\n",
) -> str:
    return (
        "- name: x\n"
        "  ansible.builtin.shell:\n"
        "    cmd: >-\n"
        "      IFS= read -r X && export X && container exec -i -e X\n"
        f"      {{{{ {container} }}}} tool\n"
        "    stdin: s\n"
        f'  delegate_to: "{{{{ {delegate} }}}}"\n'
        f"{tail}"
    )


def _gated_exec_lines(
    sources: dict[str, str], entered: tuple[str, ...] = ()
) -> dict[str, list[int]]:
    with tempfile.TemporaryDirectory() as tmp:
        tasks_dir = Path(tmp) / "tasks"
        docs: list[tuple[Path, yaml.Node]] = []
        for name, text in sources.items():
            path = tasks_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            docs.append((path, yaml.compose(text, Loader=yaml.SafeLoader)))
        graph = _ResolverGraph(
            tuple(docs), tasks_dir, frozenset(tasks_dir / name for name in entered)
        )
        found: dict[str, list[int]] = {}
        for name, text in sources.items():
            ranges = graph.gated_ranges(tasks_dir / name)
            found[name] = [
                line_no
                for line_no, line in enumerate(text.splitlines(), 1)
                if _EXEC.search(line) and any(s <= line_no <= e for s, e in ranges)
            ]
        return found


def _single(content: str) -> list[int]:
    return _gated_exec_lines({"main.yml": content})["main.yml"]


class TestHostNodeDelegateGate(unittest.TestCase):
    def test_a_task_run_once_on_a_resolved_host_node_is_gated(self) -> None:
        self.assertEqual(
            _single(_resolve_include("APP") + _exec_task("APP_HOST_NODE")), [7]
        )

    def test_other_delegates_and_unresolved_prefixes_stay_ungated(self) -> None:
        content = (
            _resolve_include("APP")
            + _exec_task("APP_HOST_NODE")
            + _exec_task("APP_TARGET")
            + _exec_task("OTHER_HOST_NODE", "OTHER_LOCAL_CID")
            + _exec_task("STACK_HOST")
        )
        self.assertEqual(_single(content), [7])

    def test_without_the_resolver_include_the_host_node_is_ungated(self) -> None:
        self.assertEqual(_single(_exec_task("APP_HOST_NODE")), [])

    def test_a_resolver_include_after_the_task_does_not_count(self) -> None:
        self.assertEqual(
            _single(_exec_task("APP_HOST_NODE") + _resolve_include("APP")), []
        )

    def test_a_resolver_include_in_rescue_or_always_does_not_count(self) -> None:
        for section in ("rescue", "always"):
            content = (
                "- block:\n"
                "    - ansible.builtin.command: probe\n"
                f"  {section}:\n"
                "    - ansible.builtin.include_tasks: "
                f"\"{{{{ lookup('path_absolute', '{_RESOLVE_HOST_CID}') }}}}\"\n"
                "      vars:\n"
                "        resolve_output_prefix: APP\n" + _exec_task("APP_HOST_NODE")
            )
            with self.subTest(section=section):
                self.assertEqual(_single(content), [])

    def test_a_resolver_include_in_a_rescued_or_conditional_block_does_not_count(
        self,
    ) -> None:
        nested = (
            "    - ansible.builtin.include_tasks: "
            f"\"{{{{ lookup('path_absolute', '{_RESOLVE_HOST_CID}') }}}}\"\n"
            "      vars:\n"
            "        resolve_output_prefix: APP\n"
        )
        rescued = (
            "- block:\n" + nested + "  rescue:\n    - ansible.builtin.command: x\n"
        )
        conditional = "- when: x | bool\n  block:\n" + nested
        plain = "- block:\n" + nested
        task = _exec_task("APP_HOST_NODE")
        self.assertEqual(_single(rescued + task), [])
        self.assertEqual(_single(conditional + task), [])
        self.assertEqual(_single(plain + task), [8])

    def test_a_resolver_include_with_its_own_when_or_loop_does_not_count(self) -> None:
        for extra in ("  when: x | bool\n", "  loop: [1]\n"):
            content = _resolve_include("APP", extra) + _exec_task("APP_HOST_NODE")
            with self.subTest(extra=extra):
                self.assertEqual(_single(content), [])

    def test_a_conditional_include_of_the_resolver_file_does_not_count(self) -> None:
        found = _gated_exec_lines(
            {
                "main.yml": (
                    "- ansible.builtin.include_tasks: resolve.yml\n"
                    "  when: x | bool\n"
                    "- ansible.builtin.include_tasks: child.yml\n"
                ),
                "resolve.yml": _resolve_include("APP"),
                "child.yml": _exec_task("APP_HOST_NODE"),
            }
        )
        self.assertEqual(found["child.yml"], [])

    def test_an_unconditional_resolver_file_ahead_of_a_conditional_include_counts(
        self,
    ) -> None:
        found = _gated_exec_lines(
            {
                "main.yml": (
                    "- ansible.builtin.include_tasks: resolve.yml\n"
                    "- ansible.builtin.include_tasks: child.yml\n"
                    "  when: x | bool\n"
                ),
                "resolve.yml": _resolve_include("APP"),
                "child.yml": _exec_task("APP_HOST_NODE"),
            }
        )
        self.assertEqual(found["child.yml"], [4])

    def test_the_resolver_must_run_ahead_on_every_include_chain(self) -> None:
        found = _gated_exec_lines(
            {
                "main.yml": (
                    "- ansible.builtin.include_tasks: early.yml\n"
                    "- ansible.builtin.include_tasks: resolve.yml\n"
                    "- ansible.builtin.include_tasks: child.yml\n"
                ),
                "resolve.yml": _resolve_include("APP"),
                "early.yml": "- ansible.builtin.include_tasks: shared.yml\n",
                "child.yml": "- ansible.builtin.include_tasks: shared.yml\n",
                "shared.yml": _exec_task("APP_HOST_NODE"),
                "late.yml": _exec_task("APP_HOST_NODE"),
            }
        )
        self.assertEqual(found["shared.yml"], [])
        self.assertEqual(found["late.yml"], [])

    def test_a_file_entered_from_outside_the_role_starts_unresolved(self) -> None:
        sources = {
            "main.yml": (
                _resolve_include("APP") + "- ansible.builtin.include_tasks: child.yml\n"
            ),
            "child.yml": _exec_task("APP_HOST_NODE"),
        }
        self.assertEqual(_gated_exec_lines(sources)["child.yml"], [4])
        self.assertEqual(_gated_exec_lines(sources, ("child.yml",))["child.yml"], [])

    def test_an_exec_into_another_container_stays_ungated(self) -> None:
        for container in (
            "lookup('container_address', 'app') ",
            "APP_CONTAINER | quote",
            "OTHER_LOCAL_CID",
        ):
            content = _resolve_include("APP") + _exec_task("APP_HOST_NODE", container)
            with self.subTest(container=container):
                self.assertEqual(_single(content), [])

    def test_every_exec_of_the_task_must_enter_the_local_container(self) -> None:
        content = _resolve_include("APP") + (
            "- ansible.builtin.shell: >-\n"
            "    container exec {{ APP_LOCAL_CID }} a &&\n"
            "    container exec -u root app_db b\n"
            '  delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
        )
        self.assertEqual(_single(content), [])

    def test_exec_options_with_values_are_skipped_before_the_operand(self) -> None:
        content = _resolve_include("APP") + (
            "- ansible.builtin.shell: >-\n"
            "    container exec -i -u root -e A=b --workdir /x\n"
            '    "{{ APP_LOCAL_CID }}" tool\n'
            '  delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
        )
        self.assertEqual(_single(content), [5])

    def test_a_nested_task_overriding_delegate_to_stays_ungated(self) -> None:
        content = _resolve_include("APP") + (
            '- delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
            "  block:\n"
            "    - ansible.builtin.shell: container exec {{ APP_LOCAL_CID }} a\n"
            "    - ansible.builtin.shell: container exec {{ APP_LOCAL_CID }} b\n"
            '      delegate_to: "{{ STACK_HOST }}"\n'
        )
        self.assertEqual(_single(content), [7])

    def test_a_task_without_run_once_stays_ungated(self) -> None:
        bare = _resolve_include("APP") + _exec_task("APP_HOST_NODE", tail="")
        off = _resolve_include("APP") + _exec_task(
            "APP_HOST_NODE", tail="  run_once: false\n"
        )
        self.assertEqual(_single(bare), [])
        self.assertEqual(_single(off), [])

    def test_run_once_on_the_enclosing_block_counts(self) -> None:
        content = _resolve_include("APP") + (
            "- run_once: true\n"
            "  block:\n"
            "    - ansible.builtin.shell: container exec {{ APP_LOCAL_CID }} a\n"
            '      delegate_to: "{{ APP_HOST_NODE }}"\n'
        )
        self.assertEqual(_single(content), [6])

    def test_run_once_from_the_apply_of_every_include_counts(self) -> None:
        task = _exec_task("APP_HOST_NODE", tail="")
        applied = (
            "- ansible.builtin.include_tasks:\n"
            "    file: child.yml\n"
            "    apply:\n"
            "      run_once: true\n"
        )
        once = {
            "main.yml": _resolve_include("APP") + applied,
            "child.yml": task,
        }
        mixed = {
            "main.yml": (
                _resolve_include("APP")
                + applied
                + "- ansible.builtin.include_tasks: child.yml\n"
            ),
            "child.yml": task,
        }
        self.assertEqual(_gated_exec_lines(once)["child.yml"], [4])
        self.assertEqual(_gated_exec_lines(mixed)["child.yml"], [])

    def test_a_resolver_include_whose_apply_may_skip_it_does_not_count(self) -> None:
        for apply in (
            "      when: x | bool\n",
            "      tags: [never]\n",
            "      vars:\n        resolve_output_prefix: OTHER\n",
        ):
            content = (
                "- ansible.builtin.include_tasks:\n"
                f"    file: \"{{{{ lookup('path_absolute', '{_RESOLVE_HOST_CID}') }}}}\"\n"
                "    apply:\n"
                f"{apply}"
                "  vars:\n"
                "    resolve_output_prefix: APP\n" + _exec_task("APP_HOST_NODE")
            )
            with self.subTest(apply=apply):
                self.assertEqual(_single(content), [])

    def test_a_resolver_include_ignoring_errors_or_tagged_never_does_not_count(
        self,
    ) -> None:
        for extra in (
            "  ignore_errors: true\n",
            "  tags: never\n",
            "  with_items: [1]\n",
        ):
            content = _resolve_include("APP", extra) + _exec_task("APP_HOST_NODE")
            with self.subTest(extra=extra):
                self.assertEqual(_single(content), [])

    def test_only_the_exact_resolver_path_counts(self) -> None:
        for path in (
            f"{_RESOLVE_HOST_CID}.disabled",
            f"{{{{ '{_RESOLVE_HOST_CID}' if x else 'other.yml' }}}}",
            f"roles/x/{_RESOLVE_HOST_CID}",
        ):
            content = (
                f'- ansible.builtin.include_tasks: "{path}"\n'
                "  vars:\n"
                "    resolve_output_prefix: APP\n" + _exec_task("APP_HOST_NODE")
            )
            with self.subTest(path=path):
                self.assertEqual(_single(content), [])

    def test_only_a_literal_prefix_counts(self) -> None:
        content = _resolve_include("\"{{ 'APP' }}\"") + _exec_task("APP_HOST_NODE")
        self.assertEqual(_single(content), [])

    def test_a_later_fact_or_var_for_the_local_cid_cancels_the_resolver(self) -> None:
        overwrite = "- ansible.builtin.set_fact:\n    APP_LOCAL_CID: other\n"
        registered = "- ansible.builtin.command: probe\n  register: APP_HOST_NODE\n"
        task_vars = _exec_task(
            "APP_HOST_NODE", tail="  run_once: true\n  vars:\n    APP_LOCAL_CID: x\n"
        )
        block_vars = (
            "- vars:\n    APP_HOST_NODE: other\n  block:\n"
            "    - ansible.builtin.shell: container exec {{ APP_LOCAL_CID }} a\n"
            '      delegate_to: "{{ APP_HOST_NODE }}"\n'
            "      run_once: true\n"
        )
        for content in (
            _resolve_include("APP") + overwrite + _exec_task("APP_HOST_NODE"),
            _resolve_include("APP") + registered + _exec_task("APP_HOST_NODE"),
            _resolve_include("APP") + task_vars,
            _resolve_include("APP") + block_vars,
        ):
            with self.subTest(content=content):
                self.assertEqual(_single(content), [])

    def test_an_exec_outside_the_command_or_inside_jinja_stays_ungated(self) -> None:
        in_vars = _resolve_include("APP") + (
            "- ansible.builtin.shell:\n"
            "    cmd: container exec {{ APP_LOCAL_CID }} a\n"
            "  vars:\n"
            "    other: container exec app_db b\n"
            '  delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
        )
        in_jinja = _resolve_include("APP") + (
            "- ansible.builtin.shell: >-\n"
            "    {{ 'container exec' }} app_db b &&\n"
            "    container exec {{ APP_LOCAL_CID }} a\n"
            '  delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
        )
        self.assertEqual(_single(in_vars), [5])
        self.assertEqual(_single(in_jinja), [])

    def test_the_local_cid_must_be_the_whole_operand_expression(self) -> None:
        for container in (
            "APP_LOCAL_CID | default('app')",
            "APP_LOCAL_CID if x else 'app'",
            "APP_LOCAL_CID and OTHER",
        ):
            content = _resolve_include("APP") + _exec_task("APP_HOST_NODE", container)
            with self.subTest(container=container):
                self.assertEqual(_single(content), [])
        for container in ("APP_LOCAL_CID", "APP_LOCAL_CID | trim | quote"):
            content = _resolve_include("APP") + _exec_task("APP_HOST_NODE", container)
            with self.subTest(container=container):
                self.assertEqual(_single(content), [7])

    def test_a_quoted_env_value_with_a_space_is_one_option_value(self) -> None:
        content = _resolve_include("APP") + (
            "- ansible.builtin.shell: >-\n"
            '    container exec -i -e "MODE=a b" {{ APP_LOCAL_CID | quote }} tool\n'
            '  delegate_to: "{{ APP_HOST_NODE }}"\n'
            "  run_once: true\n"
        )
        self.assertEqual(_single(content), [5])


class TestTasksEnteredBy(unittest.TestCase):
    def test_path_absolute_includes_and_tasks_from_are_entries(self) -> None:
        content = (
            "- ansible.builtin.include_tasks: \"{{ lookup('path_absolute', "
            "'roles/a/tasks/utils/x.yml') }}\"\n"
            "- ansible.builtin.include_role:\n"
            "    name: b\n"
            "    tasks_from: utils/y\n"
            "- ansible.builtin.include_tasks: utils/z.yml\n"
        )
        self.assertEqual(
            _tasks_entered_by(content),
            {
                (PROJECT_ROOT / "roles/a/tasks/utils/x.yml").resolve(),
                (PROJECT_ROOT / "roles/b/tasks/utils/y.yml").resolve(),
            },
        )


class TestContainerExecStackHostGate(unittest.TestCase):
    def test_container_exec_must_be_is_stack_host_gated(self) -> None:
        findings: list[tuple[str, int, str]] = []
        role_include_cache: dict[Path, set[Path]] = {}
        role_graph_cache: dict[Path, _ResolverGraph] = {}
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
            if role_dir not in role_graph_cache:
                role_graph_cache[role_dir] = _ResolverGraph(
                    _role_task_docs(role_dir),
                    role_dir / "tasks",
                    _entered_from_outside(),
                )

            gated_ranges = _collect_gated_ranges(content) + role_graph_cache[
                role_dir
            ].gated_ranges(Path(path_str))
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
                "  - run the task with `run_once: true` and `delegate_to: "
                '"{{ <PREFIX>_HOST_NODE }}"` against `{{ <PREFIX>_LOCAL_CID }}`, '
                "after an unconditional resolve_host_cid.yml include with "
                "`resolve_output_prefix: <PREFIX>`;\n"
                "  - or, for diagnostic-only paths that should attempt on "
                "workers anyway, add `# nocheck: container-exec-stack-host"
                "-gate` on the same line or the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
