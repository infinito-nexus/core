"""Enforce that every ``container exec`` / ``docker exec`` call resolves
the target via the ``container_address`` lookup (directly or through a
constant set with it). Covers the inline shell-string form and the
``command: argv: [container, exec, ...]`` list form, where the two
verbs sit on separate lines and evade any same-line regex.

Rationale
=========
In Swarm mode ``docker stack deploy`` auto-names containers
``<stack>_<service>.<replica>.<task-id>``. Bare names like
``container exec mattermost ...`` therefore fail with
``No such container: mattermost`` on every node, including the
stack-host. The ``container_address`` lookup is the single SPOT that
returns the bare name in compose mode and a runtime-evaluated subshell
(``"$(/usr/bin/resolve-container-id mattermost)"``) in swarm mode, so
the same task body works in both deployment modes.

Per-line opt-out
================
Add ``# nocheck: container-exec-resolver`` on the same line as the
``container exec`` / ``docker exec`` call OR on the immediately
preceding non-empty line. For the ``argv:`` list form, put the marker
on the list item that holds the container target.
Legitimate uses include: ``--user`` setup
where the container is provided by an upstream tool (rare), and
diagnostic scripts that already accept a resolved container ID as
parameter (the resolution happened earlier).
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

_RULE = "container-exec-resolver"

_EXEC_PROLOGUE = re.compile(r"\b(?:container|docker)\s+exec\b")

_VALUED_FLAGS = frozenset(
    {
        "-u",
        "--user",
        "-e",
        "--env",
        "-w",
        "--workdir",
        "--env-file",
        "--detach-keys",
    }
)

_JINJA_EXPR = re.compile(r"\{\{\s*(?P<expr>[^}]+?)\s*\}\}")

_DIRECT_LOOKUP = re.compile(
    r"lookup\(\s*['\"]container_address['\"]"
    r"|lookup\(\s*['\"]database['\"][^)]*['\"]address['\"]"
)

_VAR_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DEFAULT_FLAG_VALUES_THAT_ARE_NOT_NAMES = frozenset(
    {"-i", "-t", "-it", "-ti", "--interactive", "--tty"}
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if rel_path.endswith((".yml", ".yaml")) and (
        "/tasks/" in rel_path
        or "/vars/" in rel_path
        or "/defaults/" in rel_path
        or "/handlers/" in rel_path
    ):
        return True
    return "/templates/" in rel_path and rel_path.endswith(".j2")


def _is_vars_file(rel_path: str) -> bool:
    return rel_path.startswith("roles/") and (
        "/vars/" in rel_path or "/defaults/" in rel_path
    )


def _collect_approved_variables() -> set[str]:
    """Walk every ``roles/*/vars/`` and ``roles/*/defaults/`` YAML file
    and return the set of variable names whose value contains a
    ``lookup('container_address', ...)`` expression. Those variables
    are then trusted when they appear inside ``container exec`` /
    ``docker exec`` calls — they're the SPOT-compliant indirection
    layer."""
    approved: set[str] = set()
    for path_str, _content in iter_project_files_with_content(
        extensions=(".yml", ".yaml")
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not _is_vars_file(rel):
            continue
        try:
            data = load_yaml_any(path_str, default_if_missing={}) or {}
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            if _DIRECT_LOOKUP.search(value):
                approved.add(key)
    return approved


def _classify_target(token: str, approved: set[str]) -> str:
    """Decide whether *token* is OK, an unresolved Jinja, or a literal."""
    jinja = _JINJA_EXPR.search(token)
    if jinja:
        expr = jinja.group("expr").strip()
        if _DIRECT_LOOKUP.search(expr):
            return "ok-direct-lookup"
        root = re.match(r"[A-Za-z_][A-Za-z0-9_]*", expr)
        if root and root.group(0) in approved:
            return "ok-approved-var"
        return f"unapproved-jinja:{expr}"
    if _VAR_REFERENCE.match(token):
        return f"bare-literal:{token}"
    return f"non-jinja-target:{token}"


def _consume_value(rest: str, idx: int) -> int:
    """Skip a flag value starting at idx. A value may embed one or more
    ``{{...}}`` expressions (whose internal whitespace must NOT end the
    token). Returns the index after the consumed value."""
    while idx < len(rest) and rest[idx].isspace():
        idx += 1
    if idx >= len(rest):
        return idx
    while idx < len(rest) and not rest[idx].isspace():
        if rest[idx : idx + 2] == "{{":
            end = rest.find("}}", idx)
            if end < 0:
                return len(rest)
            idx = end + 2
            continue
        idx += 1
    return idx


def _extract_target(rest: str) -> str | None:
    """Walk the slice that follows ``container exec`` token-by-token,
    skipping flags (and their values where required), and return the
    first non-flag token -- the container target. Returns None if the
    line ends before a target appears (e.g. line continuation)."""
    idx = 0
    while idx < len(rest):
        while idx < len(rest) and rest[idx].isspace():
            idx += 1
        if idx >= len(rest):
            return None
        if rest[idx] == "\\" and (idx + 1 >= len(rest) or rest[idx + 1].isspace()):
            return None
        if rest[idx] == "-":
            j = idx + 1
            while j < len(rest) and not rest[j].isspace() and rest[j] != "=":
                j += 1
            flag = rest[idx:j]
            idx = j
            if idx < len(rest) and rest[idx] == "=":
                idx += 1
                if rest[idx : idx + 2] == "{{":
                    end = rest.find("}}", idx)
                    idx = end + 2 if end >= 0 else len(rest)
                else:
                    while idx < len(rest) and not rest[idx].isspace():
                        idx += 1
            elif flag in _VALUED_FLAGS:
                idx = _consume_value(rest, idx)
            continue
        if rest[idx : idx + 2] == "{{":
            end = rest.find("}}", idx)
            return rest[idx : end + 2] if end >= 0 else None
        if rest[idx] in ('"', "'"):
            quote = rest[idx]
            end = rest.find(quote, idx + 1)
            return rest[idx + 1 : end] if end >= 0 else None
        j = idx
        while j < len(rest) and not rest[j].isspace() and rest[j] not in "|;&<>(){}":
            j += 1
        return rest[idx:j]
    return None


_ARGV_EXEC_BINARIES = frozenset({"container", "docker"})


def _collect_argv_item_lists(node: yaml.Node, out: list[list[tuple[int, str]]]) -> None:
    """Append the ``(line_no, value)`` scalar items of every ``argv:``
    sequence beneath *node*. Walks the whole node tree so tasks nested
    in ``block``/``rescue``/``always`` are covered."""
    if isinstance(node, yaml.SequenceNode):
        for item in node.value:
            _collect_argv_item_lists(item, out)
        return
    if not isinstance(node, yaml.MappingNode):
        return
    for key, value in node.value:
        if (
            isinstance(key, yaml.ScalarNode)
            and key.value == "argv"
            and isinstance(value, yaml.SequenceNode)
        ):
            out.append(
                [
                    (element.start_mark.line + 1, element.value)
                    for element in value.value
                    if isinstance(element, yaml.ScalarNode)
                ]
            )
        else:
            _collect_argv_item_lists(value, out)


def _argv_exec_target(items: list[tuple[int, str]]) -> tuple[int, str] | None:
    """Return ``(line_no, token)`` of the container target when *items*
    spell ``(container|docker) exec [flags...] <target> ...``, else None."""
    if len(items) < 3:
        return None
    if items[0][1] not in _ARGV_EXEC_BINARIES or items[1][1] != "exec":
        return None
    idx = 2
    while idx < len(items):
        value = items[idx][1]
        if value.startswith("-"):
            flag = value.split("=", 1)[0]
            idx += 2 if ("=" not in value and flag in _VALUED_FLAGS) else 1
            continue
        return items[idx]
    return None


def _scan_argv_blocks(
    rel_path: str,
    content: str,
    lines: list[str],
    approved: set[str],
    findings: list[tuple[str, int, str]],
) -> None:
    if not (
        rel_path.endswith((".yml", ".yaml"))
        and ("/tasks/" in rel_path or "/handlers/" in rel_path)
    ):
        return
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return
    item_lists: list[list[tuple[int, str]]] = []
    for doc in docs:
        if doc is not None:
            _collect_argv_item_lists(doc, item_lists)
    for items in item_lists:
        target = _argv_exec_target(items)
        if target is None:
            continue
        line_no, token = target
        if _classify_target(token, approved).startswith("ok-"):
            continue
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        findings.append((rel_path, line_no, lines[line_no - 1].strip()))


def _is_comment_line(line: str) -> bool:
    return line.lstrip().startswith(("#", "//"))


_NAME_LINE = re.compile(r"^\s*-?\s*name\s*:")


def _is_yaml_name_line(line: str) -> bool:
    return bool(_NAME_LINE.match(line))


def _scan_line(
    rel_path: str,
    line_no: int,
    line: str,
    lines: list[str],
    approved: set[str],
    findings: list[tuple[str, int, str]],
) -> None:
    if _is_comment_line(line):
        return
    if _is_yaml_name_line(line):
        return
    for match in _EXEC_PROLOGUE.finditer(line):
        rest = line[match.end() :]
        target = _extract_target(rest)
        if not target:
            continue
        verdict = _classify_target(target, approved)
        if verdict.startswith("ok-"):
            continue
        if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
            continue
        findings.append((rel_path, line_no, line.strip()))


class TestContainerExecUsesResolver(unittest.TestCase):
    def test_every_container_exec_routes_through_resolver(self) -> None:
        approved = _collect_approved_variables()
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml", ".j2"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines):
                _scan_line(rel, idx + 1, line, lines, approved, findings)
            _scan_argv_blocks(rel, content, lines, approved, findings)

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    set(findings), key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found `container exec` / `docker exec` calls that do "
                "NOT route the target through the container_address "
                "lookup. Bare service names break in Swarm mode because "
                "docker stack deploy auto-suffixes container names with "
                "the task ID.\n\n"
                "Fix: define a variable in vars/main.yml whose value is "
                "the lookup, then reference it:\n\n"
                "    # roles/<role>/vars/main.yml\n"
                "    X_EXEC_ADDR: \"{{ lookup('container_address', "
                "application_id, 'x') }}\"\n\n"
                "    # roles/<role>/tasks/...yml\n"
                "    - shell: container exec -i {{ X_EXEC_ADDR }} cmd\n\n"
                "Or, where the indirection genuinely does not apply "
                "(diagnostic scripts that already carry a resolved ID, "
                "etc.), add `# nocheck: container-exec-resolver` on the "
                "same line or the line immediately above (for `argv:` "
                "lists: on the container target item).\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
