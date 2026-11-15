from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_all, load_yaml_all_str
from utils.roles.mapping import ROLE_FILE_TASKS_MCP

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator
GUARD = 'IFS= read -r {name} || :; : "${{{name}:?{message}}}"'
_MESSAGE = "arrived empty on stdin"
_YAML_EXTENSIONS = (".yml", ".yaml")
_EXTENSIONS = (*_YAML_EXTENSIONS, ".sh", ".bash", ".j2")
_SCOPES = ("roles/", "tasks/", "playbooks/")
_YAML_CONDITIONAL = re.compile(
    r'\bread\s+-r\s+([A-Za-z_]\w*)[ \t]*\|\|\s*:(?:[ \t]+:)?[ \t]+"\$\{\1:?\?'
)
_SHELL_CONDITIONAL = re.compile(
    r'\bread\s+-r\s+([A-Za-z_]\w*)[ \t]*\|\|(?:\s|\\\n)*:[ \t]+"\$\{\1:?\?'
)
_READ = re.compile(
    r"\bread[ \t]+(?:-[A-Za-z]+[ \t]+)*-r[ \t]+(?:-[A-Za-z]+[ \t]+)*"
    r"(?P<names>[A-Za-z_]\w*(?:[ \t]+[A-Za-z_]\w*)*)"
)
_LOOP_OR_PIPE_BEFORE = re.compile(
    r"(?:\b(?:while|until)[ \t]+(?:![ \t]+)?|(?<!\|)\|[ \t]*)"
    r"(?:[A-Za-z_]\w*=\S*[ \t]+)*$"
)
_REDIRECT_AFTER = re.compile(r"[ \t]*\d*<")

_MAY_BE_EMPTY: dict[tuple[str, str], str] = {
    ("roles/web-app-espocrm/tasks/01_patch_config.yml", "CONFIG_VALUE"): (
        "an empty config value is a legitimate setting; patch_config_key.sh "
        "checks only that the variable is set"
    ),
    ("roles/web-app-erpnext/tasks/addons/email_account.yml", "SMTP_PASS"): (
        "ERPNEXT_MAIL.password defaults to empty for a relay without authentication"
    ),
    (f"roles/web-app-jellyfin/{ROLE_FILE_TASKS_MCP}", "MCP_TOKEN"): (
        "MCP_UPSTREAM_CURRENT_KEY is empty on the first mint, before any upstream key exists"
    ),
    ("roles/web-app-snipe-it/tasks/utils/mcp_mint.yml", "MCP_CURRENT_TOKEN"): (
        "MCP_UPSTREAM_CURRENT_KEY is empty on the first mint, before any upstream key exists"
    ),
    ("roles/web-app-openproject/tasks/addons/gitlab_integration.yml", "OPENPROJECT_GITLAB_API_TOKEN"): (
        "OPENPROJECT_GITLAB_TOKEN_HELD is empty until the first run mints the GitLab token; "
        "ensure_gitlab_webhook.rb mints one when it reads an empty value"
    ),
    ("roles/web-app-nextcloud/tasks/addons/integration_gitlab_provision.yml", "NC_HAS_SECRET"): (
        "the stored client secret is empty until the integration is first provisioned"
    ),
    ("roles/web-app-nextcloud/tasks/addons/integration_zammad_provision.yml", "NC_HAS_SECRET"): (
        "the stored client secret is empty until the integration is first provisioned"
    ),
}


def _strings(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def _texts(content: str, documents: list | None) -> list[str]:
    return [content] if documents is None else list(_strings(documents))


def conditional_guards(content: str, documents: list | None) -> list[str]:
    """
    Args:
        content: the raw text of a task file, vars file, template or script.
        documents: the parsed YAML documents of that file, or None for a
            script, a template or YAML that does not parse.

    Returns:
        the NAME of every ``read -r NAME`` whose ``${NAME:?…}`` check runs
        only when ``read`` fails, judged on the parsed scalars of YAML so a
        folded block is read as the shell receives it.
    """
    pattern = _SHELL_CONDITIONAL if documents is None else _YAML_CONDITIONAL
    return [
        match.group(1)
        for text in _texts(content, documents)
        for match in pattern.finditer(text)
    ]


def unguarded_reads(content: str, documents: list | None) -> list[str]:
    """
    Args:
        content: the raw text of a task file, vars file, template or script.
        documents: the parsed YAML documents of that file, or None for a
            script, a template or YAML that does not parse.

    Returns:
        every NAME a ``read -r`` takes from the shell's own stdin with no
        ``${NAME:?`` check, quoted or not, after it in the same scalar or
        script; a read in a loop condition, after a pipe or from a
        redirection reads no handed-over value and is left out.
    """
    missing: list[str] = []
    for text in _texts(content, documents):
        for match in _READ.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            if _LOOP_OR_PIPE_BEFORE.search(text[line_start : match.start()]):
                continue
            if _REDIRECT_AFTER.match(text, match.end()):
                continue
            rest = text[match.end() :]
            missing.extend(
                name
                for name in match.group("names").split()
                if not re.search(rf"\$\{{{name}:\?", rest)
            )
    return missing


@cache
def _scan() -> tuple[tuple[str, ...], tuple[str, ...], frozenset[tuple[str, str]]]:
    conditional: list[str] = []
    unguarded: list[str] = []
    allowed: set[tuple[str, str]] = set()
    for path_str, content in iter_project_files_with_content(
        extensions=_EXTENSIONS, exclude_tests=True
    ):
        if "read" not in content:
            continue
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith(_SCOPES):
            continue
        documents = None
        if rel.endswith(_YAML_EXTENSIONS):
            try:
                documents = load_yaml_all(path_str)
            except Exception:  # pragma: no cover
                documents = None
        conditional.extend(
            f"- {rel}: read -r {name}"
            for name in conditional_guards(content, documents)
        )
        for name in unguarded_reads(content, documents):
            if (rel, name) in _MAY_BE_EMPTY:
                allowed.add((rel, name))
            else:
                unguarded.append(f"- {rel}: read -r {name}")
    return tuple(conditional), tuple(unguarded), frozenset(allowed)


def _yaml(text: str) -> list:
    return load_yaml_all_str(text)


class TestConditionalGuards(unittest.TestCase):
    def test_the_check_behind_a_failed_read_is_flagged(self) -> None:
        one_line = (
            "- shell: >-\n"
            '    IFS= read -r X || : "${X:?empty}" && export X && run\n'
        )
        split = (
            "- shell: >-\n"
            "    IFS= read -r X ||\n"
            '    : "${X:?empty}" && export X && run\n'
        )
        folded_two_lines = (
            "- shell: >-\n"
            "    IFS= read -r X || :\n"
            '    : "${X:?empty}" && export X && run\n'
        )
        self.assertEqual(conditional_guards(one_line, _yaml(one_line)), ["X"])
        self.assertEqual(conditional_guards(split, _yaml(split)), ["X"])
        self.assertEqual(
            conditional_guards(folded_two_lines, _yaml(folded_two_lines)), ["X"]
        )

    def test_an_unconditional_check_passes(self) -> None:
        folded = (
            "- shell: >-\n"
            f"    {GUARD.format(name='X', message='empty')} && export X && run\n"
        )
        literal = (
            "- shell: |\n"
            "    IFS= read -r X || :\n"
            '    : "${X:?empty}"\n'
            "    export X\n"
        )
        self.assertEqual(conditional_guards(folded, _yaml(folded)), [])
        self.assertEqual(conditional_guards(literal, _yaml(literal)), [])

    def test_a_script_is_read_line_by_line(self) -> None:
        old = 'IFS= read -r X || : "${X:?empty}"\n'
        continued = 'IFS= read -r X ||\n  : "${X:?empty}"\n'
        new = 'IFS= read -r X || :\n: "${X:?empty}"\n'
        self.assertEqual(conditional_guards(old, None), ["X"])
        self.assertEqual(conditional_guards(continued, None), ["X"])
        self.assertEqual(conditional_guards(new, None), [])


class TestUnguardedReads(unittest.TestCase):
    def test_a_read_without_any_check_is_flagged(self) -> None:
        task = "- shell: >-\n    IFS= read -r X && export X && run\n"
        self.assertEqual(unguarded_reads(task, _yaml(task)), ["X"])
        self.assertEqual(unguarded_reads("IFS= read -r X\nrun\n", None), ["X"])

    def test_a_check_without_the_colon_lets_an_empty_value_through(self) -> None:
        task = '- shell: >-\n    IFS= read -r X || :; : "${X?empty}" && run\n'
        self.assertEqual(unguarded_reads(task, _yaml(task)), ["X"])

    def test_every_name_of_a_multi_value_read_needs_its_own_check(self) -> None:
        task = (
            "- shell: >-\n"
            "    IFS= read -r A && IFS= read -r B &&\n"
            '    : "${A:?empty}" && export A B && run\n'
        )
        both = (
            "IFS= read -r A && IFS= read -r B &&\n"
            ': "${A:?empty}" && : ${B:?empty} && run\n'
        )
        self.assertEqual(unguarded_reads(task, _yaml(task)), ["B"])
        self.assertEqual(unguarded_reads(both, None), [])

    def test_a_check_before_the_read_does_not_count(self) -> None:
        script = ': "${X:?empty}"\nIFS= read -r X\nrun\n'
        self.assertEqual(unguarded_reads(script, None), ["X"])

    def test_loops_pipes_and_redirections_read_no_handed_over_value(self) -> None:
        script = (
            "while IFS= read -r line; do echo \"$line\"; done\n"
            "printf 'a|b\\n' | while IFS='|' read -r a b; do :; done\n"
            "printf 'x' | read -r piped\n"
            'read -r first rest <<< "$value"\n'
            "IFS= read -r from_file < /etc/hostname\n"
        )
        self.assertEqual(unguarded_reads(script, None), [])

    def test_the_guarded_forms_pass(self) -> None:
        folded = (
            "- shell: >-\n"
            f"    {GUARD.format(name='X', message='empty')} && export X && run\n"
        )
        literal = (
            "- shell: |\n"
            "    set -euo pipefail\n"
            "    IFS= read -r X\n"
            '    : "${X:?empty}"\n'
            "    export X\n"
        )
        self.assertEqual(unguarded_reads(folded, _yaml(folded)), [])
        self.assertEqual(unguarded_reads(literal, _yaml(literal)), [])


class TestGuardBehaviour(unittest.TestCase):
    def _run(self, shell: str, script: str, stdin: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [shell, "-c", script],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    def _shells(self) -> list[str]:
        shells = [shell for shell in ("sh", "dash", "bash") if shutil.which(shell)]
        if not shells:
            self.skipTest("needs sh, dash or bash")
        return shells

    def test_the_guard_fails_on_an_empty_line_and_keeps_any_value(self) -> None:
        guard = GUARD.format(name="X", message=_MESSAGE)
        for shell in self._shells():
            for prefix in ("", "set -e; ", "set -eu; "):
                script = f'{prefix}{guard}; printf "%s" "$X"'
                with self.subTest(shell=shell, prefix=prefix):
                    empty = self._run(shell, script, "\n")
                    self.assertNotEqual(empty.returncode, 0)
                    self.assertIn(_MESSAGE, empty.stderr)
                    self.assertEqual(empty.stdout, "")

                    missing = self._run(shell, script, "")
                    self.assertNotEqual(missing.returncode, 0)
                    self.assertIn(_MESSAGE, missing.stderr)

                    with_newline = self._run(shell, script, "s3cr et\n")
                    self.assertEqual(with_newline.returncode, 0, with_newline.stderr)
                    self.assertEqual(with_newline.stdout, "s3cr et")

                    without_newline = self._run(shell, script, "s3cr et")
                    self.assertEqual(
                        without_newline.returncode, 0, without_newline.stderr
                    )
                    self.assertEqual(without_newline.stdout, "s3cr et")

    def test_a_multi_value_read_fails_on_any_empty_line(self) -> None:
        script = (
            "IFS= read -r A && IFS= read -r B && "
            f': "${{A:?{_MESSAGE}}}" && : "${{B:?{_MESSAGE}}}" && '
            'printf "%s|%s" "$A" "$B"'
        )
        for shell in self._shells():
            with self.subTest(shell=shell):
                self.assertEqual(self._run(shell, script, "a\nb\n").stdout, "a|b")
                for stdin in ("\nb\n", "a\n\n"):
                    result = self._run(shell, script, stdin)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(_MESSAGE, result.stderr)

    def test_the_conditional_shape_lets_an_empty_line_through(self) -> None:
        script = f'IFS= read -r X || : "${{X:?{_MESSAGE}}}"; printf "<%s>" "$X"'
        for shell in self._shells():
            with self.subTest(shell=shell):
                result = self._run(shell, script, "\n")
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "<>")


class TestStdinGuardIsUnconditional(unittest.TestCase):
    def test_no_stdin_guard_runs_only_when_read_fails(self) -> None:
        conditional, _, _ = _scan()
        self.assertFalse(
            conditional,
            "An empty-stdin guard runs only when `read` fails. Ansible appends "
            "a newline to `stdin:`, so an empty secret arrives as an empty "
            "line, `read` succeeds and the command runs on without the "
            "credential. Check whatever `read` returns: "
            f"`{GUARD.format(name='NAME', message='…')}` (in a shell script "
            "or a literal block the check may stand on the next line)."
            "\n\nOffenders:\n" + "\n".join(conditional),
        )

    def test_every_value_read_from_stdin_is_checked_for_empty(self) -> None:
        _, unguarded, _ = _scan()
        self.assertFalse(
            unguarded,
            "A value read from stdin is used without a `${NAME:?…}` check "
            "after the read, so an empty secret runs the command without the "
            "credential. Add the check after the read, one per name of a "
            "multi-value read, or list a value that may legitimately be empty "
            "in _MAY_BE_EMPTY with its reason."
            "\n\nOffenders:\n" + "\n".join(unguarded),
        )

    def test_every_may_be_empty_entry_still_matches_a_read(self) -> None:
        _, _, allowed = _scan()
        stale = sorted(set(_MAY_BE_EMPTY) - allowed)
        self.assertFalse(
            stale,
            "These _MAY_BE_EMPTY entries match no unchecked read any more; "
            f"drop them: {stale}",
        )


if __name__ == "__main__":
    unittest.main()
