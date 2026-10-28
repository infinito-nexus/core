from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT
from .test_compose_argv_no_secret import _CREDENTIAL, _EXPRESSION, _indent

_RULE = "task-argv-secret"

_MODULE_KEY = re.compile(
    r"^(?P<indent>\s*(?:-\s+)?)(?:ansible\.builtin\.)?(?:script|command|shell)\s*:"
)
_STDIN_KEY = re.compile(r"^(?P<indent>\s*)stdin\s*:")
_EXEC = re.compile(
    r"\b(?:container|docker)\b[\s\S]{0,80}?\b(?:exec|run)\b|_EXEC_[A-Z]|_EXEC\b"
)
_FILE_REFERENCE = re.compile(
    r"^\s*lookup\(\s*['\"](?:file|path_absolute|template)['\"]"
)
_CREDENTIAL_SUFFIX = re.compile(r"(?i)_(?:pw|pass)\b")
_DESCRIBES_CREDENTIAL = re.compile(
    r"(?i)(?:password|passwd|pwd|secret|token|api_?key|private_?key|credential)\w*"
    r"_(?:file|path|dir|id|ids|name|names|user|username|owner|email|hash|length"
    r"|days|description|url|uri|host|port|type|enabled)\b"
)


def _module_blocks(lines: list[str]) -> list[list[int]]:
    """Group a task file's lines into the bodies of command-running modules.

    Args:
      lines: the task file's lines.

    Returns:
      one list of 0-based line indexes per ``script``, ``command`` or
      ``shell`` module, its ``stdin:`` value left out.
    """
    blocks: list[list[int]] = []
    index = 0
    while index < len(lines):
        key = _MODULE_KEY.match(lines[index])
        if not key:
            index += 1
            continue
        indent = len(key.group("indent"))
        block = [index]
        stdin_indent: int | None = None
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.strip() and _indent(line) <= indent:
                break
            if (
                stdin_indent is not None
                and line.strip()
                and _indent(line) <= stdin_indent
            ):
                stdin_indent = None
            stdin = _STDIN_KEY.match(line)
            if stdin:
                stdin_indent = len(stdin.group("indent"))
            elif stdin_indent is None:
                block.append(index)
            index += 1
        blocks.append(block)
    return blocks


def _argv_secret_lines(lines: list[str]) -> list[int]:
    """Return the 1-based lines that render a credential into a task's argv.

    Args:
      lines: the task file's lines.

    Returns:
      every line of a ``script``, ``command`` or ``shell`` module whose Jinja
      expression names a credential; modules that run ``container exec`` or
      ``docker run`` are left to the exec-argv rules.
    """
    found: list[int] = []
    for block in _module_blocks(lines):
        if _EXEC.search("\n".join(lines[i] for i in block)):
            continue
        for i in block:
            for expression in _EXPRESSION.findall(lines[i]):
                if _FILE_REFERENCE.search(expression):
                    continue
                names_credential = _CREDENTIAL.search(
                    expression
                ) or _CREDENTIAL_SUFFIX.search(expression)
                if names_credential and not _DESCRIBES_CREDENTIAL.search(expression):
                    found.append(i + 1)
                    break
    return found


class TestArgvSecretLines(unittest.TestCase):
    def test_a_positional_script_argument_is_flagged(self) -> None:
        lines = [
            "- ansible.builtin.script: >-",
            "    set_pw.sh {{ ADDRESS | quote }}",
            "    {{ POSTGRES_PASSWORD | quote }}",
        ]
        self.assertEqual(_argv_secret_lines(lines), [3])

    def test_a_pw_or_pass_suffix_is_flagged(self) -> None:
        lines = [
            "  command: >",
            "    ldapsm -W '{{ OPENLDAP_BIND_PW }}'",
            "    --admin {{ KEYCLOAK_ADMIN_PASS }}",
        ]
        self.assertEqual(_argv_secret_lines(lines), [2, 3])

    def test_stdin_environment_and_exec_lines_pass(self) -> None:
        lines = [
            "- ansible.builtin.command:",
            "    argv: [cli, login]",
            "    stdin: '{{ ADMIN_PASSWORD }}'",
            "  environment:",
            "    TOKEN: '{{ API_TOKEN }}'",
            "- ansible.builtin.shell: >-",
            "    container exec app cli --pass {{ ADMIN_PASSWORD }}",
            "- ansible.builtin.command: cli --lifetime {{ MCP_TOKEN_LIFETIME_DAYS }}",
        ]
        self.assertEqual(_argv_secret_lines(lines), [])


class TestTaskArgvNoSecret(unittest.TestCase):
    def test_task_argv_renders_no_credential(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/") or not (
                "/tasks/" in rel or "/handlers/" in rel
            ):
                continue
            lines = content.splitlines()
            findings.extend(
                f"- {rel}:{line_no}: {lines[line_no - 1].strip()}"
                for line_no in _argv_secret_lines(lines)
                if not is_suppressed_at(lines, line_no, _RULE, mode="same-or-above")
            )

        self.assertFalse(
            findings,
            "A credential is rendered into the command line of a script, command "
            "or shell task, where the host's `ps` shows it to every local account "
            "while the call runs and `no_log` cannot mask it. Pass it on the "
            "module's `stdin:` and read it there; a task-level `environment:` "
            "does not help, Ansible prefixes it to its own `/bin/sh -c` command "
            "line. Mark a deliberate exception with "
            f"`# nocheck: {_RULE}`.\n\nOffenders:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
