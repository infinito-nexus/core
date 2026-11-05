from __future__ import annotations

import re
import unittest
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plugins.lookup.role_templates_expanded import DEFAULTS as RENDERER_DEFAULTS
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.invocations import iter_tasks
from utils.roles.mapping import (
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Callable

COMPOSE_ROLE = "sys-svc-compose"
COMPOSE_FILES_STEP = PROJECT_ROOT / "roles" / COMPOSE_ROLE / "tasks" / "04_files.yml"

SOURCES: dict[str, tuple[str, ...]] = {
    "dockerfile": ("templates/Dockerfile.j2", "files/Dockerfile"),
    "env": ("templates/env.j2", "files/env"),
    "compose_override": (
        "templates/compose.override.yml.j2",
        "files/compose.override.yml",
    ),
    "compose": (ROLE_FILE_TEMPL_COMPOSE,),
}
EXCLUSIVE: frozenset[str] = frozenset({"dockerfile"})
INSTANCE_FILES: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "compose.yml": "compose",
    "compose.override.yml": "compose_override",
}
ENV_DIR_FILES: dict[str, str] = {"env": "env"}

_PREFIXES = ("", "ansible.builtin.", "ansible.legacy.")
WRITE_MODULES: tuple[str, ...] = (
    *(
        prefix + name
        for name in ("copy", "template", "lineinfile", "blockinfile", "replace")
        for prefix in _PREFIXES
    ),
    "stack_host_copy",
    "stack_host_template",
)
ATTRIBUTE_MODULES: tuple[str, ...] = tuple(prefix + "file" for prefix in _PREFIXES)
INCLUDE_MODULES: tuple[str, ...] = tuple(
    prefix + name for name in ("include_tasks", "import_tasks") for prefix in _PREFIXES
)
RENDERER = "render_replicated_templates.yml"
PATH_KEYS = ("dest", "path", "name")
SKIPPED_STATES = ("directory", "absent", "link")
LOOP_KEYS = ("loop", "with_items", "with_list")

_EXPRESSION = re.compile(r"\s*\{\{\s*(?P<expr>.*?)\s*\}\}\s*", re.DOTALL)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CONTAINER = (
    r"lookup\(\s*['\"]container['\"]\s*,\s*application_id\s*,\s*['\"]{key}['\"]\s*\)"
)
_FILES_LOOKUP = re.compile(_CONTAINER.format(key=r"files\.(?P<key>\w+)"))
_INSTANCE_LOOKUP = re.compile(_CONTAINER.format(key=r"directories\.instance"))
_ENV_DIR_LOOKUP = re.compile(_CONTAINER.format(key=r"directories\.env"))
_PATH_JOIN = re.compile(
    r"\[\s*(?P<base>.+?)\s*,\s*['\"](?P<name>[^'\"]+)['\"]\s*\]\s*\|\s*path_join"
)
_CONCAT = re.compile(r"\{\{\s*(?P<base>.+?)\s*\}\}/?(?P<name>[\w.]+)")


def _expression(raw: Any) -> str | None:
    """
    Args:
        raw: a YAML scalar.

    Returns:
        the whitespace-normalised Jinja expression when *raw* is exactly one
        ``{{ ... }}`` block, else ``None``.
    """
    if not isinstance(raw, str):
        return None
    match = _EXPRESSION.fullmatch(raw)
    return " ".join(match.group("expr").split()) if match else None


def _resolve(expr: str, variables: dict[str, str]) -> str:
    """
    Args:
        expr: a normalised Jinja expression.
        variables: variable name to its normalised expression.

    Returns:
        *expr* with a bare variable name followed to the expression it names.
    """
    for _ in range(10):
        if not _IDENTIFIER.fullmatch(expr) or expr not in variables:
            return expr
        expr = variables[expr]
    return expr


def target_of(raw: Any, variables: dict[str, str]) -> str | None:
    """
    Args:
        raw: the dest or path a task writes.
        variables: variable name to its normalised expression.

    Returns:
        the ``files.<key>`` of ``utils/docker/paths_utils.py`` *raw* names, or
        ``None`` when it names none of them.
    """
    expr = _expression(raw)
    if expr is None:
        concat = _CONCAT.fullmatch(raw.strip()) if isinstance(raw, str) else None
        if concat is None:
            return None
        base = _resolve(" ".join(concat.group("base").split()), variables)
        if _INSTANCE_LOOKUP.fullmatch(base):
            return INSTANCE_FILES.get(concat.group("name"))
        return None
    expr = _resolve(expr, variables)
    files = _FILES_LOOKUP.fullmatch(expr)
    if files:
        return files.group("key")
    joined = _PATH_JOIN.fullmatch(expr)
    if joined is None:
        return None
    base = _resolve(joined.group("base"), variables)
    if _INSTANCE_LOOKUP.fullmatch(base):
        return INSTANCE_FILES.get(joined.group("name"))
    if _ENV_DIR_LOOKUP.fullmatch(base):
        return ENV_DIR_FILES.get(joined.group("name"))
    return None


def _quoted_attribute(values: dict[str, str]) -> Callable[[re.Match[str]], str]:
    """
    Args:
        values: the string attributes of one loop item.

    Returns:
        a ``re.sub`` replacement that swaps ``<loop_var>.<attr>`` for the
        quoted attribute value.
    """
    return lambda match: repr(values[match.group("attr")])


def _expand_loop(task: dict[str, Any], raw: Any) -> list[tuple[Any, str]]:
    """
    Args:
        task: the task that writes *raw*.
        raw: the dest or path as the task spells it.

    Returns:
        ``(dest, needle)`` per literal loop item the dest reads, or *raw*
        itself when the task does not loop over literal items.
    """
    loop = next((task[key] for key in LOOP_KEYS if key in task), None)
    if not isinstance(loop, list) or not isinstance(raw, str):
        return [(raw, str(raw))]
    control = task.get("loop_control")
    loop_var = control.get("loop_var", "item") if isinstance(control, dict) else "item"
    attribute = re.compile(rf"(?<![\w.]){re.escape(loop_var)}\.(?P<attr>\w+)")
    bare = re.compile(rf"\{{\{{\s*{re.escape(loop_var)}\s*\}}\}}")
    expanded: list[tuple[Any, str]] = []
    for item in loop:
        if isinstance(item, str) and bare.fullmatch(raw.strip()):
            expanded.append((item, item))
        elif isinstance(item, dict):
            values = {k: v for k, v in item.items() if isinstance(v, str)}
            used = [m.group("attr") for m in attribute.finditer(raw)]
            if not used or any(attr not in values for attr in used):
                continue
            dest = attribute.sub(_quoted_attribute(values), raw)
            expanded.append((dest, values[used[-1]]))
    return expanded or [(raw, str(raw))]


def writes(tasks: Any) -> list[tuple[str, Any, Any, str]]:
    """
    Args:
        tasks: a parsed task file.

    Returns:
        ``(task name, dest, mode, needle)`` for every file a task writes or
        sets attributes on, including the entries handed to
        ``render_replicated_templates.yml``. ``mode`` is ``None`` when the
        task leaves the mode alone.
    """
    found: list[tuple[str, Any, Any, str]] = []
    for task in iter_tasks(tasks):
        name = str(task.get("name", ""))
        for module in WRITE_MODULES + ATTRIBUTE_MODULES:
            args = task.get(module)
            if not isinstance(args, dict):
                continue
            if module in ATTRIBUTE_MODULES and args.get("state") in SKIPPED_STATES:
                continue
            raw = next((args[key] for key in PATH_KEYS if key in args), None)
            for dest, needle in _expand_loop(task, raw):
                found.append((name, dest, args.get("mode"), needle))
        for module in INCLUDE_MODULES:
            spec = task.get(module)
            target = spec.get("file") if isinstance(spec, dict) else spec
            if not isinstance(target, str) or RENDERER not in target:
                continue
            entries = (task.get("vars") or {}).get("role_templates") or []
            for entry in entries:
                if isinstance(entry, dict) and "dest" in entry:
                    mode = entry.get("mode", RENDERER_DEFAULTS["mode"])
                    found.append((name, entry["dest"], mode, str(entry["dest"])))
    return found


@cache
def compose_modes() -> dict[str, str]:
    """
    Returns:
        ``files.<key>`` to the mode ``04_files.yml`` renders it with.
    """
    modes: dict[str, str] = {}
    for task in iter_tasks(load_yaml_any(str(COMPOSE_FILES_STEP))):
        args = task.get("stack_host_template")
        if not isinstance(args, dict):
            continue
        match = _FILES_LOOKUP.search(str(args.get("dest", "")))
        if match:
            modes[match.group("key")] = str(args.get("mode"))
    return modes


def role_variables(role_dir: Path) -> dict[str, str]:
    """
    Args:
        role_dir: the role directory.

    Returns:
        every top-level variable of the role's ``vars/main.yml`` whose value
        is one Jinja expression, mapped to that expression.
    """
    data = load_yaml_any(str(role_dir / ROLE_FILE_VARS_MAIN), default_if_missing={})
    if not isinstance(data, dict):
        return {}
    found: dict[str, str] = {}
    for key, value in data.items():
        expr = _expression(value)
        if expr is not None:
            found[str(key)] = expr
    return found


def managed_keys(role_dir: Path) -> set[str]:
    """
    Args:
        role_dir: the role directory.

    Returns:
        the ``files.<key>`` sys-svc-compose renders for the role, read from
        the sources the role ships.
    """
    return {
        key
        for key, candidates in SOURCES.items()
        if any((role_dir / candidate).is_file() for candidate in candidates)
    }


def _line(lines: list[str], name: str, needle: str) -> int:
    start = 0
    if name:
        start = next(
            (
                index
                for index, line in enumerate(lines)
                if name in line and line.lstrip().startswith(("- name:", "name:"))
            ),
            0,
        )
    for index in range(start, len(lines)):
        if needle in lines[index]:
            return index + 1
    return start + 1


def violations(
    role: str,
    rel: str,
    tasks: Any,
    lines: list[str],
    keys: set[str],
    variables: dict[str, str],
    modes: dict[str, str],
) -> list[str]:
    """
    Args:
        role: the role name.
        rel: the task file, relative to the project root.
        tasks: the parsed task file.
        lines: the task file's lines.
        keys: the ``files.<key>`` sys-svc-compose renders for the role.
        variables: the role's variables, name to normalised expression.
        modes: ``files.<key>`` to the mode sys-svc-compose renders it with.

    Returns:
        one ``file:line: reason`` per task that writes a file sys-svc-compose
        already writes for the role.
    """
    found: list[str] = []
    for name, dest, mode, needle in writes(tasks):
        key = target_of(dest, variables)
        if key is None or key not in keys:
            continue
        line = _line(lines, name, needle)
        if key in EXCLUSIVE:
            found.append(
                f"{rel}:{line}: {role} writes files.{key}, which {COMPOSE_ROLE} "
                f"already renders from {' or '.join(SOURCES[key])}"
            )
        elif mode is not None and str(mode) != modes[key]:
            found.append(
                f"{rel}:{line}: {role} sets mode {mode} on files.{key}, which "
                f"{COMPOSE_ROLE} renders with mode {modes[key]}"
            )
    return found


class TestComposeFileSingleWriter(unittest.TestCase):
    def test_compose_renders_every_managed_file(self) -> None:
        text = read_text(str(COMPOSE_FILES_STEP))
        self.assertEqual(sorted(compose_modes()), sorted(SOURCES))
        for candidates in SOURCES.values():
            for candidate in candidates:
                self.assertIn(Path(candidate).name, text)

    def test_roles_leave_compose_files_to_sys_svc_compose(self) -> None:
        modes = compose_modes()
        found: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if role_dir.name == COMPOSE_ROLE or not (role_dir / "tasks").is_dir():
                continue
            keys = managed_keys(role_dir)
            if not keys:
                continue
            variables = role_variables(role_dir)
            for path in sorted((role_dir / "tasks").rglob("*.yml")):
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                found.extend(
                    violations(
                        role_dir.name,
                        rel,
                        load_yaml_any(str(path)),
                        read_text(str(path)).splitlines(),
                        keys,
                        variables,
                        modes,
                    )
                )
        if found:
            self.fail(
                "These role tasks write a file sys-svc-compose already writes for "
                "the same application, so both report changed on every deploy and "
                "notify compose-build/compose-up:\n"
                + "\n".join(f"- {entry}" for entry in found)
                + "\n\nFix: drop the second write and let "
                "roles/sys-svc-compose/tasks/04_files.yml render the file, or set "
                "the mode sys-svc-compose uses."
            )

    def test_a_looped_dockerfile_copy_is_found(self) -> None:
        tasks = [
            {
                "name": "stage",
                "stack_host_copy": {
                    "src": "{{ item.src }}",
                    "dest": "{{ [ lookup('container', application_id, 'directories.instance'), item.dest ] | path_join }}",
                    "mode": "0644",
                },
                "loop": [
                    {"src": "Dockerfile", "dest": "Dockerfile"},
                    {"src": "a.py", "dest": "a.py"},
                ],
            }
        ]
        lines = ["- name: stage", '    - { src: "Dockerfile", dest: "Dockerfile" }']
        rel = f"roles/web-app-x/{ROLE_FILE_TASKS_MAIN}"
        found = violations(
            "web-app-x", rel, tasks, lines, {"dockerfile"}, {}, {"dockerfile": "0640"}
        )
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith(f"{rel}:2: web-app-x"))

    def test_an_env_mode_flip_through_a_variable_is_found(self) -> None:
        variables = {"X_ENV": "lookup('container', application_id, 'files.env')"}
        flip = [{"file": {"path": "{{ X_ENV }}", "owner": "33", "mode": "0660"}}]
        same = [{"file": {"path": "{{ X_ENV }}", "owner": "33", "mode": "0640"}}]
        modes = {"env": "0640"}
        self.assertEqual(
            len(violations("r", "f", flip, [], {"env"}, variables, modes)), 1
        )
        self.assertEqual(violations("r", "f", same, [], {"env"}, variables, modes), [])

    def test_a_rerender_with_the_compose_mode_passes(self) -> None:
        tasks = [
            {
                "ansible.builtin.include_tasks": {
                    "file": f"roles/{COMPOSE_ROLE}/tasks/utils/{RENDERER}"
                },
                "vars": {
                    "role_templates": [
                        {
                            "src": "env.j2",
                            "dest": "{{ lookup('container', application_id, 'files.env') }}",
                        }
                    ]
                },
            }
        ]
        self.assertEqual(
            violations("r", "f", tasks, [], {"env"}, {}, {"env": "0640"}), []
        )


if __name__ == "__main__":
    unittest.main()
