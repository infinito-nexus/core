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
  ``argv: [bash, -lc, ...]`` escape hatch) names ``container`` or
  ``docker`` with a subcommand that takes a container reference
  (``exec``, ``restart``, ``stop``, ``start``, ``kill``, ``rm``,
  ``pause``, ``unpause``, ``logs``, ``cp``, ``inspect``, ``wait``,
  ``top``). The contract belongs to the lookup's ``$(...)`` output, not
  to ``exec``: a ``container restart`` of the same target under
  ``command:`` failed the same way in
  ``svc-ai-libretranslate-engine/tasks/utils/install_models.yml``,
  which an ``exec``-only pattern did not catch;
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
_EXEC = re.compile(
    r"\b(?:container|docker)\s+"
    r"(?:exec|restart|stop|start|kill|rm|pause|unpause|logs|cp|inspect|wait|top)\b"
)
_JINJA = re.compile(r"\{\{[^}]+\}\}")
_COMMAND_MODULES = frozenset({"command", "ansible.builtin.command"})
_EXEC_VERB = re.compile(r"\b(?:container|docker)\s+exec\b")
_ADDRESS_SOURCE = re.compile(
    r"lookup\(\s*'container_address'"
    r"|lookup\(\s*'database'\s*,[^)]*,\s*'address'\s*\)"
)


def _variable_values() -> dict[str, str]:
    """Every string-valued var the roles and group_vars declare, by name."""
    values: dict[str, str] = {}
    for pattern in ("roles/*/vars/*.yml", "group_vars/**/*.yml"):
        for path in PROJECT_ROOT.glob(pattern):
            data = load_yaml_any(str(path), default_if_missing={})
            if isinstance(data, dict):
                values.update(
                    {str(k): v for k, v in data.items() if isinstance(v, str)}
                )
    return values


def _shell_variables(values: dict[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    """Split the vars that carry the swarm ``$(...)`` payload by how they do.

    Args:
        values: var name to its declared string value.

    Returns:
        The address vars, whose value is a lookup emitting ``$(...)`` and
        which oblige ``shell`` only when a container verb uses them, and the
        exec vars, whose value already is a ``container exec`` of such an
        address and which oblige ``shell`` wherever a ``command:`` names them.
    """
    address = frozenset(
        name
        for name, value in values.items()
        if _ADDRESS_SOURCE.search(value) and not _EXEC.search(value)
    )
    exec_ = frozenset(
        name
        for name, value in values.items()
        if _EXEC.search(value)
        and (_ADDRESS_SOURCE.search(value) or any(a in value for a in address))
    )
    return address, exec_


_ADDRESS_NAMES, _EXEC_NAMES = _shell_variables(_variable_values())


def _needs_shell(body: str) -> bool:
    """Whether ``body`` under ``command:`` would pass unevaluated shell syntax."""
    if any(name in body for name in _EXEC_NAMES):
        return True
    if any(name in body for name in _ADDRESS_NAMES):
        return bool(_EXEC.search(body))
    return bool(_EXEC_VERB.search(body) and _JINJA.search(body))


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
        if body and _needs_shell(body):
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


class TestShellPayloadVariables(unittest.TestCase):
    def test_a_database_address_obliges_shell_like_a_container_address(self) -> None:
        address, _ = _shell_variables(
            {"X_DB": "{{ lookup('database', application_id, 'address') }}"}
        )
        self.assertEqual(address, frozenset({"X_DB"}))

    def test_a_var_wrapping_the_whole_exec_is_caught_by_its_name(self) -> None:
        _, exec_ = _shell_variables(
            {
                "X_PSQL": (
                    "container exec -i {{ lookup('database', application_id, "
                    "'address') }} psql"
                )
            }
        )
        self.assertEqual(exec_, frozenset({"X_PSQL"}))

    def test_a_literal_container_name_obliges_nothing(self) -> None:
        self.assertEqual(
            _shell_variables({"X_CONTAINER": "x-app"}), (frozenset(), frozenset())
        )

    def test_the_listmonk_design_body_under_command_is_flagged(self) -> None:
        self.assertTrue(_needs_shell("{{ LISTMONK_EXEC_DATABASE }} -v ON_ERROR_STOP=1"))


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
