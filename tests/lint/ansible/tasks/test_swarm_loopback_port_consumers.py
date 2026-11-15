"""Lint: every host-side reader of a loopback port says how swarm reaches it.

Swarm publishes no ``ports.local`` port, so a task that reads one, or
``DOCKER_REACH_HOST``, directly or through a role or ``group_vars`` variable,
reaches nothing there. So does a task that names a loopback host in one value
and a local port in another (``login_host`` beside ``login_port``), and a
``templates/**/*.env.j2`` that hands such a value to a host-side test. A read
passes when its ``when:`` (or an enclosing block's, or every include site of
its file) holds only outside swarm, when an env template renders it only in a
compose branch, when it hands the value to the vhost, or when the role pins
itself to compose. Every other read carries
``# nocheck: swarm-loopback-port <exec|overlay|netns|unused|open> <reason>`` on
its line, in the comment block directly above it or above its task;
``# nocheck: swarm-loopback-port file <category> <reason>`` in the file's
leading comment block covers every read of the file. A marker that covers no
such read is dead.
Scope: ``roles/*/tasks/**/*.yml``, the shared ``tasks/**/*.yml`` and
``roles/*/templates/**/*.env.j2``.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from functools import cache
from pathlib import Path
from typing import NamedTuple

import yaml

from utils.annotations.suppress import marker_reason, suppressed_line_numbers
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)
from utils.roles.swarm_loopback import (
    COMPOSE,
    compose_pinned,
    condition_mode,
    in_compose_branch,
    is_vhost_input,
    role_variables,
)
from utils.roles.swarm_loopback_markers import (
    CATEGORIES,
    RULE,
    attached_marker,
    marker_scope,
    reason_problem,
)
from utils.roles.swarm_loopback_reads import (
    _closure,
    blinded,
    definition_markers,
    flattened,
    grown,
    loopback_names,
    names_pattern,
    read_pattern,
    split_patterns,
)

from . import PROJECT_ROOT

_COMMENT = re.compile(r"^\s*(?:#|\{#)")
_HEAD_COMMENT = re.compile(r"^\s*(?:\{#.*#\}|#.*)\s*$")
_NAME_LINE = re.compile(r"^\s*(?:-\s+)?name:")
_KEY = re.compile(r"^\s*(?:-\s+)?([\w.-]+):(?=\s|$)")
_PLACEMENT_KEYS = frozenset({"delegate_to", "hosts", "connection"})
_INCLUDE_KEYS = (
    "ansible.builtin.include_tasks",
    "include_tasks",
    "ansible.builtin.import_tasks",
    "import_tasks",
)
_ROLE_PATH = re.compile(r"^\{\{\s*role_path\s*\}\}/tasks/(.+)$")
_PATH_ABSOLUTE = re.compile(
    r"""^\{\{\s*lookup\(\s*['"]path_absolute['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}$"""
)


def _children(node: yaml.MappingNode) -> dict[str, yaml.Node]:
    return {
        key.value: value
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    }


def _node_value(node: yaml.Node | None) -> object:
    if isinstance(node, yaml.ScalarNode):
        return node.value
    if isinstance(node, yaml.SequenceNode):
        return [_node_value(item) for item in node.value]
    return None


def _task_ranges(
    node: yaml.Node, gated: bool, ranges: list[tuple[int, int, bool, bool]]
) -> None:
    """Collects ``(first line, last line, compose-gated, leaf)`` of every task and block."""
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _task_ranges(item, gated, ranges)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    children = _children(node)
    here = gated or condition_mode(_node_value(children.get("when"))) == COMPOSE
    nested = [key for key in ("block", "rescue", "always") if key in children]
    ranges.append((node.start_mark.line + 1, node.end_mark.line, here, not nested))
    for key in nested:
        if isinstance(children[key], yaml.SequenceNode):
            _task_ranges(children[key], here, ranges)


def _code(line: str) -> str:
    """Returns the value part of a YAML line, without its key and its trailing comment."""
    match = _KEY.match(line)
    value = line[match.end() :] if match else line
    quote = ""
    for index, char in enumerate(value):
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


def _is_code(line: str) -> bool:
    return not (_COMMENT.match(line) or _NAME_LINE.match(line) or is_vhost_input(line))


def _is_placement(line: str) -> bool:
    match = _KEY.match(line)
    return bool(match) and match.group(1) in _PLACEMENT_KEYS


def _head_lines(lines: list[str]) -> set[int]:
    """Returns the line numbers of the file's leading comment block."""
    head: set[int] = set()
    for number, line in enumerate(lines, start=1):
        if line.strip() in ("", "---") and not head:
            continue
        if not _HEAD_COMMENT.match(line):
            return head
        head.add(number)
    return head


def _file_marker(lines: list[str], head: set[int]) -> tuple[int, str] | None:
    """Returns the ``file`` marker of the leading comment block, which covers the whole file."""
    for number in sorted(head):
        reason = marker_reason(lines[number - 1], RULE)
        if reason is not None and marker_scope(reason.removesuffix("#}"))[0]:
            return number, reason.removesuffix("#}").strip()
    return None


def _checkout_of(tasks_dir: Path) -> Path:
    role_dir = tasks_dir.parent
    return role_dir.parent.parent if role_dir.parent.name == "roles" else role_dir


def _normal(path: Path) -> Path:
    return Path(os.path.normpath(path))


def _resolved(include: object, tasks_dir: Path, including: Path) -> set[Path]:
    """Returns the files an include from *including* may load; none for a templated one."""
    if isinstance(include, dict):
        include = include.get("file", "")
    include = str(include).strip()
    role_path = _ROLE_PATH.match(include)
    if role_path:
        return {_normal(tasks_dir / role_path.group(1))}
    absolute = _PATH_ABSOLUTE.match(include)
    if absolute:
        return {_normal(_checkout_of(tasks_dir) / absolute.group(1))}
    if not include or "{{" in include or "{%" in include:
        return set()
    return {_normal(tasks_dir / include), _normal(including.parent / include)}


def _include_sites(
    tasks: object, target: Path, tasks_dir: Path, including: Path
) -> list[bool]:
    """Returns, per include of *target* in a task list, whether the site is compose-gated.

    Args:
        tasks: the loaded task list of *including*.
        target: the included file.
        tasks_dir: the tasks directory both files belong to.
        including: the file holding *tasks*.
    """
    sites: list[bool] = []
    if not isinstance(tasks, list):
        return sites
    for task in tasks:
        if not isinstance(task, dict):
            continue
        gated = condition_mode(task.get("when")) == COMPOSE
        for key in ("block", "rescue", "always"):
            sites.extend(
                gated or site
                for site in _include_sites(task.get(key), target, tasks_dir, including)
            )
        included = next((task[key] for key in _INCLUDE_KEYS if key in task), None)
        if included is not None and _normal(target) in _resolved(
            included, tasks_dir, including
        ):
            sites.append(gated)
    return sites


@cache
def _yml_files(directory: Path) -> tuple[Path, ...]:
    return tuple(sorted(directory.rglob("*.yml")))  # nocheck: project-walk  fixtures


def _file_gated(
    tasks_dir: Path, path: Path, seen: frozenset[Path] = frozenset()
) -> bool:
    """Whether every include of *path* is compose-gated, itself or through its including file.

    The entry file ``tasks/main.yml`` runs without an include, so it never is.
    """
    if path == tasks_dir.parent / ROLE_FILE_TASKS_MAIN:
        return False
    sites = [
        (site, other)
        for other in _yml_files(tasks_dir)
        if other != path
        for site in _include_sites(
            load_yaml_any(str(other), default_if_missing=[]), path, tasks_dir, other
        )
    ]
    return bool(sites) and all(
        gated or (other not in seen and _file_gated(tasks_dir, other, seen | {path}))
        for gated, other in sites
    )


def _global_values(project_root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted((project_root / "group_vars" / "all").glob("*.yml")):
        values.update(flattened(load_yaml_any(str(path), default_if_missing={}) or {}))
    return values


def _task_files(project_root: Path) -> list[tuple[Path, Path, Path | None]]:
    """Returns ``(tasks dir, task file, role dir or None)`` for every scanned task file."""
    found = [
        (project_root / "tasks", path, None)
        for path in _yml_files(project_root / "tasks")
    ]
    for role_dir in _role_dirs(project_root):
        found.extend(
            (role_dir / "tasks", path, role_dir)
            for path in _yml_files(role_dir / "tasks")
        )
    return found


def _role_dirs(project_root: Path) -> list[Path]:
    return sorted(path for path in (project_root / "roles").iterdir() if path.is_dir())


def _env_templates(role_dir: Path) -> list[Path]:
    templates = role_dir / "templates"
    return sorted(templates.rglob("*.env.j2"))  # nocheck: project-walk  fixtures


def _split_reads(
    lines: list[str],
    ranges: list[tuple[int, int, bool, bool]],
    patterns: tuple[re.Pattern[str], re.Pattern[str]],
    line_hits: list[int],
) -> list[int]:
    """Returns, per leaf task without a line read, its first loopback-host line when it also names a local port."""
    hosts, ports = patterns
    hits: list[int] = []
    for start, end, _, leaf in ranges:
        if not leaf or any(start <= number <= end for number in line_hits):
            continue
        code = [
            (number, _code(lines[number - 1]))
            for number in range(start, min(end, len(lines)) + 1)
            if _is_code(lines[number - 1]) and not _is_placement(lines[number - 1])
        ]
        host_lines = [number for number, value in code if hosts.search(value)]
        if host_lines and any(ports.search(value) for _, value in code):
            hits.append(host_lines[0])
    return hits


class _Answers:
    """Matches reads to markers and collects the problems of one file.

    Args:
        rel: the file's path relative to the repository root.
        lines: the file's lines.
        requirements_dir: the ``docs/requirements`` directory ``open`` reasons cite.
    """

    def __init__(self, rel: str, lines: list[str], requirements_dir: Path) -> None:
        self.rel = rel
        self.lines = lines
        self.requirements_dir = requirements_dir
        self.head = _head_lines(lines)
        self.file_marker = _file_marker(lines, self.head)
        self.markers = suppressed_line_numbers(lines, RULE)
        self.attached: set[int] = set()
        self.problems: list[str] = []

    def answer(self, number: int, task_starts: list[int]) -> None:
        """Attaches the read on *number* to the innermost marker that covers it.

        Args:
            number: the read's line.
            task_starts: the first lines of its enclosing tasks and blocks.
        """
        marker = attached_marker(self.lines, number)
        for start in sorted(task_starts, reverse=True):
            if marker is not None:
                break
            marker = attached_marker(self.lines, start)
        if marker is None:
            marker = self.file_marker
        if marker is None:
            self.problems.append(
                f"{self.rel}:{number}: reads a loopback port that swarm does not publish; gate it on "
                f"IS_COMPOSE_MODE or mark it nocheck: {RULE} <{'|'.join(CATEGORIES)}> <reason>"
            )
            return
        self.attached.add(marker[0])

    def close(self) -> list[str]:
        for line in sorted(self.markers):
            reason = marker_reason(self.lines[line - 1], RULE)
            whole_file, rest = marker_scope((reason or "").removesuffix("#}"))
            if line not in self.attached:
                self.problems.append(
                    f"{self.rel}:{line}: dead nocheck: {RULE}, no ungated loopback read needs it"
                )
            elif whole_file and line not in self.head:
                self.problems.append(
                    f"{self.rel}:{line}: a file-wide {RULE} marker sits outside the leading comment block"
                )
            elif problem := reason_problem(rest, self.requirements_dir):
                self.problems.append(f"{self.rel}:{line}: the {RULE} marker {problem}")
        return self.problems


class _Definition(NamedTuple):
    where: str
    reason: str
    reads: re.Pattern[str]


class _Patterns(NamedTuple):
    own: re.Pattern[str]
    any: re.Pattern[str]
    split: tuple[re.Pattern[str], re.Pattern[str]]
    definitions: tuple[_Definition, ...]


def _patterns(
    values: dict[str, str], answered: dict[str, tuple[str, str]]
) -> _Patterns:
    """Returns the read patterns of one scope.

    Args:
        values: the scope's variables, ``group_vars`` and the role's.
        answered: ``{name: (file:line, reason)}`` of the definitions a marker answers.
    """
    return _Patterns(
        read_pattern(loopback_names(blinded(values, set(answered)))),
        read_pattern(loopback_names(values)),
        split_patterns(values),
        tuple(
            _Definition(where, reason, names_pattern(grown(values, {name})))
            for name, (where, reason) in sorted(answered.items())
        ),
    )


def _route(code: str, patterns: _Patterns) -> list[str] | None:
    """Returns None for a read that needs its own answer, else the definitions that answer it.

    An empty list means the line reads no loopback port at all.
    """
    if patterns.own.search(code):
        return None
    if not patterns.any.search(code):
        return []
    answering = [d.where for d in patterns.definitions if d.reads.search(code)]
    return answering or None


def _answered(project_root: Path, paths: list[Path]) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for path in paths:
        rel = path.relative_to(project_root).as_posix()
        for name, (line, reason) in definition_markers(path).items():
            found[name] = (f"{rel}:{line}", reason)
    return found


def _task_file_problems(
    project_root: Path,
    tasks_dir: Path,
    path: Path,
    patterns: _Patterns,
    used: set[str],
) -> list[str]:
    text = read_text(str(path))
    lines = text.splitlines()
    routes = {
        number: route
        for number, line in enumerate(lines, start=1)
        if _is_code(line) and (route := _route(_code(line), patterns)) != []
    }
    ranges: list[tuple[int, int, bool, bool]] = []
    try:
        for document in yaml.compose_all(text, Loader=yaml.SafeLoader):
            _task_ranges(document, False, ranges)
    except yaml.YAMLError:
        pass
    routes.update(
        dict.fromkeys(_split_reads(lines, ranges, patterns.split, list(routes)))
    )
    answers = _Answers(
        path.relative_to(project_root).as_posix(),
        lines,
        project_root / "docs" / "requirements",
    )
    if not routes and not answers.markers:
        return []
    file_gated = bool(routes) and _file_gated(tasks_dir, path)
    for number, route in sorted(routes.items()):
        enclosing = [r for r in ranges if r[0] <= number <= r[1]]
        if file_gated or any(gated for _, _, gated, _ in enclosing):
            continue
        if route is not None:
            used.update(route)
            continue
        answers.answer(number, [r[0] for r in enclosing])
    return answers.close()


def _env_problems(
    project_root: Path, path: Path, patterns: _Patterns, used: set[str]
) -> list[str]:
    text = read_text(str(path))
    lines = text.splitlines()
    answers = _Answers(
        path.relative_to(project_root).as_posix(),
        lines,
        project_root / "docs" / "requirements",
    )
    offset = 0
    for number, line in enumerate(lines, start=1):
        route = [] if _COMMENT.match(line) else _route(_code(line), patterns)
        if route != [] and not in_compose_branch(text, offset):
            if route is None:
                answers.answer(number, [])
            else:
                used.update(route)
        offset += len(line) + 1
    return answers.close()


def consumer_problems(project_root: Path) -> list[str]:
    """Returns one line per ungated loopback read without an answer and per bad or dead marker.

    A marker on a variable's definition in ``group_vars/all``, ``vars/main.yml``
    or ``defaults/main.yml`` answers every read through that variable and
    through the variables derived from it.

    Args:
        project_root: the repository root, holding ``roles/``, ``tasks/``,
            ``group_vars/`` and ``docs/requirements/``.
    """
    global_values = _global_values(project_root)
    global_answered = _answered(
        project_root, sorted((project_root / "group_vars" / "all").glob("*.yml"))
    )
    answered: dict[str, tuple[str, str]] = dict(global_answered)
    patterns: dict[Path | None, _Patterns] = {}

    def role_patterns(role_dir: Path | None) -> _Patterns:
        if role_dir not in patterns:
            local, local_answered = {}, {}
            if role_dir is not None:
                local = role_variables(role_dir)
                local_answered = _answered(
                    project_root,
                    [
                        role_dir / ROLE_FILE_DEFAULTS_MAIN,
                        role_dir / ROLE_FILE_VARS_MAIN,
                    ],
                )
                answered.update(
                    {f"{role_dir.name}:{name}": v for name, v in local_answered.items()}
                )
            patterns[role_dir] = _patterns(
                {**global_values, **local}, {**global_answered, **local_answered}
            )
        return patterns[role_dir]

    used: set[str] = set()
    problems: list[str] = []
    for tasks_dir, path, role_dir in _task_files(project_root):
        if role_dir is not None and compose_pinned(
            role_dir, path.relative_to(role_dir).as_posix()
        ):
            continue
        problems.extend(
            _task_file_problems(
                project_root, tasks_dir, path, role_patterns(role_dir), used
            )
        )
    for role_dir in _role_dirs(project_root):
        role_patterns(role_dir)
        for path in _env_templates(role_dir):
            if not compose_pinned(role_dir, path.relative_to(role_dir).as_posix()):
                problems.extend(
                    _env_problems(project_root, path, role_patterns(role_dir), used)
                )
    for where, reason in sorted(set(answered.values())):
        if where not in used:
            problems.append(
                f"{where}: dead nocheck: {RULE}, no ungated read goes through this variable"
            )
        elif problem := reason_problem(reason, project_root / "docs" / "requirements"):
            problems.append(f"{where}: the {RULE} marker {problem}")
    return problems


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_MAIN_TASKS = (
    '- name: direct\n  ansible.builtin.uri:\n    url: "http://{{ DOCKER_REACH_HOST }}:1"\n'
    '- name: through a role variable\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n'
    '- name: through group_vars\n  community.general.ldap_search:\n    server_uri: "{{ LDAP.SERVER.HOST_URI }}"\n'
    '- name: gated\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n  when: IS_COMPOSE_MODE | bool\n'
    '- name: vhost\n  ansible.builtin.include_role:\n    name: svc-stack\n  vars:\n    http_port: "{{ A_URL }}"\n'
    "- name: answered\n  ansible.builtin.uri:\n"
    "    # nocheck: swarm-loopback-port exec  the probe runs inside the container\n"
    '    url: "{{ A_URL }}"\n'
    "- name: compose only\n  ansible.builtin.include_tasks: compose.yml\n  when: IS_COMPOSE_MODE | bool\n"
    "- name: dead\n  # nocheck: swarm-loopback-port unused  nothing reads it\n  ansible.builtin.debug:\n    msg: hi\n"
    '- name: a bare port number pairs with a service name\n  ansible.builtin.debug:\n    msg: "{{ LDAP.SERVER.PORT }}"\n'
    "# nocheck: swarm-loopback-port exec  the whole task runs inside the container\n"
    '- name: task head\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n'
    '- name: split host and port\n  community.postgresql.postgresql_db:\n    login_host: "{{ A_HOST }}"\n    login_port: "{{ A_PORT }}"\n'
    '- name: an or gate confines nothing\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n  when: IS_COMPOSE_MODE or x\n'
    '- name: a negated compose gate is a swarm gate\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n  when: not IS_COMPOSE_MODE\n'
    "- name: a foreign variable is no mode\n  ansible.builtin.uri:\n    url: \"{{ A_URL }}\"\n  when: x != 'swarm'\n"
    '- name: a mode in a trailing comment exempts nothing\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"  # IS_COMPOSE_MODE\n'
    '- name: a read in a trailing comment is none\n  ansible.builtin.debug:\n    msg: "hi"  # {{ A_URL }}\n'
    "- name: open cites a done criterion\n  ansible.builtin.uri:\n"
    "    # nocheck: swarm-loopback-port open  swarm drops it; 074 :3 tracks it\n"
    '    url: "{{ A_URL }}"\n'
    "- name: open cites the open criterion\n  ansible.builtin.uri:\n"
    "    # nocheck: swarm-loopback-port open  swarm drops it; 074 :2 tracks it\n"
    '    url: "{{ A_URL }}"\n'
    "- name: the upgrade entry\n  ansible.builtin.include_tasks: upgrade/main.yml\n  when: IS_COMPOSE_MODE | bool\n"
    '- name: through a marked definition\n  ansible.builtin.uri:\n    url: "{{ A_DERIVED }}"\n'
    '- name: a host with its own port is no split read\n  ansible.builtin.uri:\n    url: "{{ A_NETNS_URL }}"\n    body: "{{ A_PORT }}"\n'
)
_UNANSWERED = (
    "direct",
    "through a role variable",
    "through group_vars",
    "split host and port",
    "an or gate confines nothing",
    "a negated compose gate is a swarm gate",
    "a foreign variable is no mode",
    "a mode in a trailing comment exempts nothing",
)


def _task_line(name: str, offset: int) -> int:
    return _MAIN_TASKS.splitlines().index(f"- name: {name}") + 1 + offset


class TestSwarmLoopbackPortConsumers(unittest.TestCase):
    def test_every_ungated_loopback_read_is_answered(self) -> None:
        problems = consumer_problems(PROJECT_ROOT)
        self.assertEqual(
            [], problems, f"{len(problems)} problem(s):\n  " + "\n  ".join(problems)
        )

    def test_the_rule_reports_each_unanswered_shape(self) -> None:
        main = f"roles/web-app-a/{ROLE_FILE_TASKS_MAIN}"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                "group_vars/all/00.yml",
                "LDAP:\n  SERVER:\n"
                "    PORT: \"{{ lookup('config', 'svc-db-openldap', 'services.openldap.ports.local.ldap') }}\"\n"
                '    HOST_URI: "ldap://{{ DOCKER_REACH_HOST }}:{{ LDAP.SERVER.PORT }}"\n'
                "# nocheck: swarm-loopback-port open  host-side readers bind it on the published port; 074 :2 tracks it\n"
                "B_URI: \"http://{{ DOCKER_REACH_HOST }}:{{ lookup('config', 'svc-b', 'services.b.ports.local.http') }}\"\n"
                "# nocheck: swarm-loopback-port unused  nothing reads it\n"
                "C_URI: \"http://{{ DOCKER_REACH_HOST }}:{{ lookup('config', 'svc-c', 'services.c.ports.local.http') }}\"\n",
            )
            _write(
                root,
                str(Path("docs", "requirements", "074-x.md")),
                "# x\n- [ ] open criterion\n- [x] done criterion\n",
            )
            _write(
                root,
                "tasks/utils/noop.yml",
                "- name: noop\n  ansible.builtin.debug:\n    msg: hi\n",
            )
            _write(
                root,
                f"roles/web-app-a/{ROLE_FILE_VARS_MAIN}",
                "A_URL: \"http://127.0.0.1:{{ lookup('config', application_id, 'services.a.ports.local.http') }}\"\n"
                'A_HOST: "127.0.0.1"\n'
                'A_DERIVED: "{{ B_URI }}/v1"\n'
                'A_NETNS_URL: "http://127.0.0.1:8080"\n'
                "A_PORT: \"{{ lookup('config', application_id, 'services.a.ports.local.db') }}\"\n",
            )
            _write(root, main, _MAIN_TASKS)
            _write(
                root,
                "roles/web-app-a/tasks/compose.yml",
                '- name: in compose\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n',
            )
            _write(
                root,
                "roles/web-app-a/tasks/upgrade/main.yml",
                '- name: in compose\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n',
            )
            _write(
                root,
                "roles/web-app-a/tasks/headed.yml",
                "---\n# nocheck: swarm-loopback-port file unused  nothing includes this file under swarm\n\n"
                '- name: x\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n'
                '- name: y\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n',
            )
            _write(
                root,
                "roles/web-app-a/tasks/task_headed.yml",
                "---\n# nocheck: swarm-loopback-port exec  the first task runs inside the container\n"
                '- name: x\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n'
                '- name: y\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n'
                "# nocheck: swarm-loopback-port file exec  a file marker below the head\n"
                '- name: z\n  ansible.builtin.uri:\n    url: "{{ A_URL }}"\n',
            )
            _write(
                root,
                "roles/web-app-a/templates/test.env.j2",
                "A_TEST_URL={{ A_URL }}\n"
                "{% if IS_COMPOSE_MODE %}\nA_DEBUG_URL={{ A_URL }}\n{% endif %}\n",
            )
            problems = consumer_problems(root)
        expected = [f"{main}:{_task_line(name, 2)}: reads" for name in _UNANSWERED] + [
            f"{main}:{_task_line('dead', 1)}: dead nocheck",
            f"{main}:{_task_line('open cites a done criterion', 2)}: the {RULE} marker cites 074 :3",
            "roles/web-app-a/tasks/task_headed.yml:8: reads",
            "roles/web-app-a/tasks/task_headed.yml:9: a file-wide",
            "roles/web-app-a/templates/test.env.j2:1: reads",
            "group_vars/all/00.yml:7: dead nocheck",
        ]
        self.assertEqual(len(expected), len(problems), problems)
        self.assertEqual(
            expected,
            [
                problem[: len(prefix)]
                for problem, prefix in zip(problems, expected, strict=True)
            ],
            problems,
        )

    def test_an_include_matches_its_resolved_path_only(self) -> None:
        tasks_dir = Path("/r/roles/web-app-a/tasks")
        including = tasks_dir / "main.yml"
        tasks = [
            {"name": "a", "include_tasks": "x.yml", "when": "IS_COMPOSE_MODE"},
            {"name": "b", "include_tasks": "x.yml"},
            {"name": "c", "include_tasks": "sub/x.yml", "when": "IS_COMPOSE_MODE"},
        ]
        self.assertEqual(
            [True, False],
            _include_sites(tasks, tasks_dir / "x.yml", tasks_dir, including),
        )
        self.assertEqual(
            [True], _include_sites(tasks, tasks_dir / "sub/x.yml", tasks_dir, including)
        )
        self.assertEqual(
            [], _include_sites(tasks, tasks_dir / "other/x.yml", tasks_dir, including)
        )

    def test_the_entry_file_and_a_suffix_namesake_stay_ungated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            tasks_dir = Path(root) / "roles" / "web-app-a" / "tasks"
            (tasks_dir / "sub").mkdir(parents=True)
            gated_include = "- include_tasks: {}\n  when: IS_COMPOSE_MODE\n"
            (tasks_dir / "main.yml").write_text(
                gated_include.format("sub/x.yml"), encoding="utf-8"
            )
            (tasks_dir / "loop.yml").write_text(
                gated_include.format("main.yml"), encoding="utf-8"
            )
            (tasks_dir / "x.yml").write_text("- debug: {}\n", encoding="utf-8")
            (tasks_dir / "sub" / "x.yml").write_text("- debug: {}\n", encoding="utf-8")
            self.assertTrue(_file_gated(tasks_dir, tasks_dir / "sub" / "x.yml"))
            self.assertFalse(_file_gated(tasks_dir, tasks_dir / "x.yml"))
            self.assertFalse(_file_gated(tasks_dir, tasks_dir / "main.yml"))

    def test_the_closure_helper_stays_importable_for_the_probes(self) -> None:
        self.assertEqual({"A"}, _closure({"A": "ports.local.x"}, re.compile("ports")))


if __name__ == "__main__":
    unittest.main()
