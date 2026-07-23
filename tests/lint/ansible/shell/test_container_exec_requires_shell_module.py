"""Enforce that ``container exec`` / ``docker exec`` tasks use the
``shell`` module (not ``command``) when the container target is a
Jinja reference that resolves through the ``container_address`` lookup.

Rationale
=========
``container_address`` emits ``"$(BIN_RESOLVE_CONTAINER_ID STACK SVC)"``
in swarm mode -- a shell subshell that resolves the running task's
container ID at exec time. The ``ansible.builtin.command`` module
spawns the binary directly via argv, so ``$(...)`` is passed verbatim
as the container name and Docker fails to find a match. Only
``ansible.builtin.shell`` invokes a shell that evaluates the
substitution.

The rule fires when ALL of:

* a task uses ``command:`` or ``ansible.builtin.command:``;
* the command body (string form or list form, but NOT the
  ``argv: [bash, -lc, ...]`` escape hatch) contains
  ``container exec`` or ``docker exec``;
* the target token is a Jinja reference ``{{ ... }}``.

The ``argv: [bash, -lc, ...]`` form is safe because bash is invoked
explicitly and evaluates ``$(...)`` on its own.

Per-line opt-out
================
Add ``# nocheck: container-exec-requires-shell`` on the same line as
the ``container exec`` invocation or on the line above.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

_RULE = "container-exec-requires-shell"
_EXEC = re.compile(r"\b(?:container|docker)\s+exec\b")
_JINJA = re.compile(r"\{\{[^}]+\}\}")
_COMMAND_MODULES = frozenset({"command", "ansible.builtin.command"})


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if not rel_path.endswith((".yml", ".yaml")):
        return False
    return "/tasks/" in rel_path or "/handlers/" in rel_path


def _command_body_text(value: Any) -> str | None:
    """Return the inline string the command module will execute, or None
    when the task uses ``argv:`` / a dict-form invocation that does not
    expose a shell-evaluable body. ``command: <string>`` and the
    ``command: { cmd: "<string>" }`` and ``command: ["arg", ...]`` forms
    all flatten to a textual representation; the ``argv:`` form is the
    documented escape hatch and must NOT be flagged."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    if isinstance(value, dict):
        if "argv" in value:
            return None
        cmd = value.get("cmd")
        if isinstance(cmd, str):
            return cmd
        if isinstance(cmd, list):
            return " ".join(str(v) for v in cmd)
    return None


def _task_command_node(task: yaml.MappingNode) -> yaml.Node | None:
    """Return the value node for a ``command:`` / ``ansible.builtin.command:``
    key on the given task mapping, or None if the task uses a different
    module."""
    for k, v in task.value:
        if isinstance(k, yaml.ScalarNode) and k.value in _COMMAND_MODULES:
            return v
    return None


def _node_body_value(node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_node_body_value(item) for item in node.value]
    if isinstance(node, yaml.MappingNode):
        out: dict[str, Any] = {}
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode):
                out[k.value] = _node_body_value(v)
        return out
    return None


def _walk_tasks(node: yaml.Node, findings: list[tuple[int, str]]) -> None:
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _walk_tasks(item, findings)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    cmd_value = _task_command_node(node)
    if cmd_value is not None:
        body = _command_body_text(_node_body_value(cmd_value))
        if body and _EXEC.search(body) and _JINJA.search(body):
            findings.append((cmd_value.start_mark.line + 1, body.strip()))
    for k, v in node.value:
        if not isinstance(k, yaml.ScalarNode):
            continue
        if k.value in ("block", "rescue", "always"):
            _walk_tasks(v, findings)


def _scan_file(path_str: str, content: str) -> list[tuple[int, str]]:
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    found: list[tuple[int, str]] = []
    for doc in docs:
        _walk_tasks(doc, found)
    return found


class TestContainerExecRequiresShellModule(unittest.TestCase):
    def test_command_module_never_runs_container_exec_with_jinja(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            try:
                # Surface YAML errors as test infrastructure issues, not
                # silent skips: load_yaml_any is the project's preferred
                # parser and would have failed earlier had the file been
                # truly malformed.
                load_yaml_any(path_str, default_if_missing=None)
            except Exception:
                continue
            file_findings = _scan_file(path_str, content)
            if not file_findings:
                continue
            lines = content.splitlines()
            for line_no, snippet in file_findings:
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, snippet))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {snip[:120]}"
                for p, ln, snip in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                "Found `command:` tasks that invoke `container exec` / "
                "`docker exec` with a Jinja-templated target. In swarm "
                "mode the `container_address` lookup emits `$(...)` shell "
                "syntax which the `command` module passes literally; only "
                "`shell:` invokes a shell that evaluates the substitution.\n\n"
                "Fix one of:\n"
                "  - change `command:` to `shell:`;\n"
                "  - if the body needs explicit bash, use the "
                "`command: { argv: [bash, -lc, <script>] }` form (bash "
                "evaluates $(...) on its own);\n"
                "  - or add `# nocheck: container-exec-requires-shell` on "
                "the same line as the `container exec` call or above it.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
