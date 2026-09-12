"""Lint: a task that carries a credential is masked by itself or by a parent.

At ``-vvv`` Ansible prints every module argument and every result, so a
credential in a command line, a request body, an environment or a fact lands in
the deploy log. A task counts as masked when any of these holds:

* it, or an enclosing ``block``/``rescue``/``always``, sets ``no_log``;
* every file that pulls it in does so through ``include_tasks`` with
  ``apply: {no_log: ...}`` or through ``import_tasks`` with ``no_log``, or sits
  in a masked parent itself (checked transitively);
* the credential only reaches a parameter the module masks on its own, or the
  module masks its values (``mask_values``).

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: credential-masking`` on, or directly above, the task's ``- name:``.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path
from typing import ClassVar

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "credential-masking"
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_SECRET = re.compile(
    r"(?i)\b[a-z0-9_]*(?:password|secret|token|api_?key|private_?key)\b(?!\s*\()"
    r"|secrets\.credentials\."
)
_TRUTHY = re.compile(r"MASK_CREDENTIALS_IN_LOGS|^\s*(?:true|yes|on)\s*$", re.IGNORECASE)
_NAME_LINE = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")
_BLOCK_KEYS = ("block", "rescue", "always")
_INCLUDE_KEYS = ("include_tasks", "ansible.builtin.include_tasks")
_IMPORT_KEYS = ("import_tasks", "ansible.builtin.import_tasks")
_SILENT_KEYS = frozenset(
    {
        "include_role",
        "import_role",
        "meta",
        "ansible.builtin.include_role",
        "ansible.builtin.import_role",
        "ansible.builtin.meta",
    }
)
_TASK_KEYWORDS = frozenset(
    {
        "name",
        "when",
        "register",
        "until",
        "changed_when",
        "failed_when",
        "no_log",
        "tags",
        "notify",
        "listen",
        "delegate_to",
        "delegate_facts",
        "run_once",
        "retries",
        "delay",
        "loop_control",
        "become",
        "become_user",
        "become_method",
        "ignore_errors",
        "ignore_unreachable",
        "vars",
        "timeout",
        "async",
        "poll",
        "check_mode",
        "diff",
        "throttle",
        "any_errors_fatal",
        "connection",
    }
)
_MODULE_MASKED_PARAMS = frozenset(
    {"url_password", "login_password", "password", "api_token", "account_api_key"}
)
_PATH_ABSOLUTE = re.compile(r"path_absolute['\"]\s*,\s*['\"]([^'\"]+)['\"]")
_ROLE_PATH = re.compile(r"\{\{\s*role_path\s*\}\}/(.+)$")


def _masks(value: object) -> bool:
    return value is not None and value is not False and bool(_TRUTHY.search(str(value)))


def _has_secret(value: object) -> bool:
    return any(_SECRET.search(span) for span in _JINJA.findall(str(value)))


def carries_unmasked_secret(task: dict) -> bool:
    """Whether a leaf task prints a credential no module masking hides.

    Args:
      task: one parsed task mapping without block keys.
    """
    for key, value in task.items():
        if key in _TASK_KEYWORDS:
            continue
        if isinstance(value, dict):
            if _masks(value.get("mask_values")):
                return False
            printed = {k: v for k, v in value.items() if k not in _MODULE_MASKED_PARAMS}
            if _has_secret(printed):
                return True
        elif _has_secret(value):
            return True
    return False


def _include_spec(task: dict) -> tuple[str, object]:
    for key in _INCLUDE_KEYS + _IMPORT_KEYS:
        if key in task:
            return key, task[key]
    return "", None


def _resolve(including: Path, spec: object, known: set[Path]) -> Path | None:
    file = spec.get("file") if isinstance(spec, dict) else spec
    if not isinstance(file, str):
        return None
    role_dir = next(
        (p.parent for p in including.parents if p.name in ("tasks", "handlers")), None
    )
    candidates = []
    absolute = _PATH_ABSOLUTE.search(file)
    role_relative = _ROLE_PATH.search(file)
    if absolute:
        candidates.append(PROJECT_ROOT / absolute.group(1))
    elif role_relative and role_dir:
        candidates.append(role_dir / role_relative.group(1))
    elif "{{" not in file:
        candidates.append(including.parent / file)
        if role_dir:
            candidates.append(role_dir / "tasks" / file)
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in known:
            return resolved
    return None


def find_leaks(tasks_by_file: dict[Path, list]) -> list[tuple[Path, str]]:
    """Return ``(file, task name)`` for every credential task no parent masks.

    Args:
      tasks_by_file: parsed task lists keyed by resolved file path.
    """
    known = set(tasks_by_file)
    includers: dict[Path, list[tuple[Path, bool]]] = defaultdict(list)
    leaks: list[tuple[Path, str]] = []

    def walk(path: Path, tasks: object, inherited: bool) -> None:
        for task in tasks if isinstance(tasks, list) else ():
            if not isinstance(task, dict):
                continue
            masked = inherited or _masks(task.get("no_log"))
            if any(key in task for key in _BLOCK_KEYS):
                for key in _BLOCK_KEYS:
                    walk(path, task.get(key), masked)
                continue
            kind, spec = _include_spec(task)
            if kind:
                target = _resolve(path, spec, known)
                if target is not None:
                    apply = spec.get("apply") if isinstance(spec, dict) else None
                    covers = (
                        masked
                        if kind in _IMPORT_KEYS
                        else (
                            inherited
                            or (isinstance(apply, dict) and _masks(apply.get("no_log")))
                        )
                    )
                    includers[target].append((path, covers))
                continue
            if _SILENT_KEYS & task.keys():
                continue
            if not masked and carries_unmasked_secret(task):
                leaks.append((path, str(task.get("name", "<unnamed>"))))

    for path, tasks in tasks_by_file.items():
        walk(path, tasks, False)

    def covered(path: Path, seen: frozenset) -> bool:
        parents = includers.get(path)
        if not parents or path in seen:
            return False
        return all(
            covers or covered(source, seen | {path}) for source, covers in parents
        )

    return [(path, name) for path, name in leaks if not covered(path, frozenset())]


def _task_files() -> dict[Path, tuple[list, list[str]]]:
    files = {}
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).relative_to(PROJECT_ROOT).parts
        if (
            len(parts) < 3
            or parts[0] != "roles"
            or parts[2] not in ("tasks", "handlers")
        ):
            continue
        data = load_yaml_str(content)
        if isinstance(data, list):
            files[Path(path).resolve()] = (data, content.splitlines())
    return files


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _name_line(lines: list[str], name: str) -> int:
    for number, line in enumerate(lines, start=1):
        match = _NAME_LINE.match(line)
        if match and _unquote(match.group(1)) == name:
            return number
    return 1


def is_suppressed(lines: list[str], name: str) -> bool:
    return is_suppressed_at(lines, _name_line(lines, name), _RULE)


def unmasked_credential_tasks() -> list[str]:
    files = _task_files()
    findings = []
    for path, name in find_leaks({p: data for p, (data, _) in files.items()}):
        lines = files[path][1]
        if is_suppressed(lines, name):
            continue
        number = _name_line(lines, name)
        rel = path.relative_to(PROJECT_ROOT.resolve())
        findings.append(f"{rel}:{number}: {name[:70]}")
    return findings


class TestCredentialTasksAreMasked(unittest.TestCase):
    def test_every_credential_task_is_masked_by_itself_or_a_parent(self) -> None:
        findings = unmasked_credential_tasks()
        self.assertEqual(
            [],
            findings,
            f"task(s) print a credential without no_log ({len(findings)}); set "
            '`no_log: "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"` on the task or a '
            "parent:\n" + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_role_task_files(self) -> None:
        self.assertGreater(len(_task_files()), 100)


class TestParentMasking(unittest.TestCase):
    ROOT = PROJECT_ROOT.resolve() / "roles/x/tasks"
    SECRET_TASK: ClassVar[dict] = {
        "name": "leak",
        "ansible.builtin.shell": "run {{ X_PASSWORD }}",
    }

    def _leaks(self, main: list, child: list | None = None) -> list[str]:
        files = {self.ROOT / "main.yml": main}
        if child is not None:
            files[self.ROOT / "child.yml"] = child
        return [name for _, name in find_leaks(files)]

    def test_an_unmasked_credential_task_is_found(self) -> None:
        self.assertEqual(self._leaks([dict(self.SECRET_TASK)]), ["leak"])

    def test_an_enclosing_block_masks(self) -> None:
        block = {
            "no_log": "{{ MASK_CREDENTIALS_IN_LOGS | bool }}",
            "block": [self.SECRET_TASK],
        }
        self.assertEqual(self._leaks([block]), [])

    def test_an_include_apply_masks_the_included_file(self) -> None:
        include = {
            "include_tasks": {
                "file": "child.yml",
                "apply": {"no_log": "{{ MASK_CREDENTIALS_IN_LOGS | bool }}"},
            }
        }
        self.assertEqual(self._leaks([include], [self.SECRET_TASK]), [])

    def test_an_import_with_no_log_masks_the_imported_file(self) -> None:
        imported = {
            "import_tasks": "child.yml",
            "no_log": "{{ MASK_CREDENTIALS_IN_LOGS | bool }}",
        }
        self.assertEqual(self._leaks([imported], [self.SECRET_TASK]), [])

    def test_no_log_on_an_include_itself_does_not_reach_the_included_file(self) -> None:
        include = {
            "include_tasks": "child.yml",
            "no_log": "{{ MASK_CREDENTIALS_IN_LOGS | bool }}",
        }
        self.assertEqual(self._leaks([include], [self.SECRET_TASK]), ["leak"])

    def test_a_parameter_the_module_masks_needs_no_no_log(self) -> None:
        task = {
            "name": "login",
            "uri": {"url": "http://x", "url_password": "{{ X_PASSWORD }}"},
        }
        self.assertEqual(self._leaks([task]), [])

    def test_a_path_that_only_names_a_secret_is_not_a_credential(self) -> None:
        task = {
            "name": "dir",
            "file": {"path": "{{ DIR_SECRETS }}", "state": "directory"},
        }
        self.assertEqual(self._leaks([task]), [])


class TestSuppression(unittest.TestCase):
    NAME = "📦 bench new-site '{{ SITE }}'"

    def test_a_marker_above_the_name_suppresses_the_task(self) -> None:
        lines = [
            "---",
            "- name: other",
            "  shell: y",
            "# nocheck: credential-masking",
            f'- name: "{self.NAME}"',
            "  shell: x",
        ]
        self.assertTrue(is_suppressed(lines, self.NAME))

    def test_a_marker_above_another_task_does_not_suppress(self) -> None:
        lines = [
            "# nocheck: credential-masking",
            "- name: other",
            "  shell: y",
            f'- name: "{self.NAME}"',
            "  shell: x",
        ]
        self.assertFalse(is_suppressed(lines, self.NAME))


if __name__ == "__main__":
    unittest.main()
