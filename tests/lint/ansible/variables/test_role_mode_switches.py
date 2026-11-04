"""Lint: a role reads the debug and validate modes only through their lookups.

``DEBUG`` and ``VALIDATE`` (``group_vars/all/01_modes.yml``) are the
deployment-wide modes, and no role file reads them. A role reads its switch as
``lookup('debug')`` / ``lookup('validate')``, which answers
``services.<entity>.<switch>.enabled`` of the role's primary entity when that is
set and the global mode otherwise. Code without an ``application_id`` of its own
(a helper role, a handler or file another role includes) names the role:
``lookup('debug', '<role>')``.

A ``debug`` / ``validate`` block under the primary entity of
``meta/services.yml`` is an optional override holding exactly ``enabled``; its
value is a literal or a template that does not read the global. A role that
declares an override but never calls the matching lookup carries dead config. A
host overrides one role at
``applications.<role>.services.<entity>.<switch>.enabled``.

A read is a mode name inside a Jinja expression or statement, or inside an
Ansible condition (``when``, ``changed_when``, ``failed_when``, ``until``,
``that``) of a YAML file; string literals inside them are not reads. Markdown
files, ``#`` comment lines and Jinja comments are not reads.
"""

from __future__ import annotations

import os
import re
import unittest
from collections.abc import Iterable, Mapping
from pathlib import PurePath

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import ROLES_DIR, iter_role_dirs
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

SWITCHES: dict[str, str] = {"debug": "DEBUG", "validate": "VALIDATE"}
YAML_SUFFIXES = frozenset({".yml", ".yaml"})
GLOBAL_NAME = re.compile(rf"(?<![\w.])(?:{'|'.join(SWITCHES.values())})(?!\w)")
JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
JINJA_BLOCK = re.compile(r"\{\{(?P<expr>.*?)\}\}|\{%(?P<stmt>.*?)%\}", re.DOTALL)
STRING_LITERAL = re.compile(r"""'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*\"""")
CONDITION = re.compile(
    r"^(?P<indent> *)(?P<item>- +)?(?:when|changed_when|failed_when|until|that)"
    r" *: *(?P<rest>.*)$"
)
BLOCK_SCALARS = frozenset({"", ">", ">-", ">+", "|", "|-", "|+"})
SWITCH_LOOKUP = re.compile(
    r"""lookup\(\s*(?P<q>['"])(?P<switch>debug|validate)(?P=q)\s*(?P<args>[^)]*)\)"""
)
LITERAL_ARG = re.compile(r"""^,\s*(?P<q>['"])(?P<role>[^'"]+)(?P=q)\s*$""")
CONFIG_READ = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,[^)]*?['"]services\.[^.'"]+\."""
    r"""(?P<switch>debug|validate)(?:\.enabled)?['"]"""
)


def _unquoted(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def reads_global(expression: str) -> bool:
    """Whether a Jinja expression names ``DEBUG`` or ``VALIDATE``.

    Args:
        expression: the body of one Jinja block or Ansible condition.
    """
    return bool(GLOBAL_NAME.search(STRING_LITERAL.sub("''", expression)))


def _condition_lines(lines: list[str]) -> list[int]:
    found: list[int] = []
    index = 0
    while index < len(lines):
        match = CONDITION.match(lines[index])
        index += 1
        if not match or lines[index - 1].lstrip().startswith("#"):
            continue
        rest = STRING_LITERAL.sub(
            lambda quoted: quoted.group(0).replace("#", ""), match.group("rest")
        )
        rest = _unquoted(rest.split(" #", 1)[0])
        if rest not in BLOCK_SCALARS:
            if reads_global(rest):
                found.append(index)
            continue
        indent = len(match.group("indent")) + len(match.group("item") or "")
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            depth = len(line) - len(line.lstrip())
            if stripped and depth < indent:
                break
            if stripped and depth == indent and not stripped.startswith("- "):
                break
            if (
                stripped
                and not stripped.startswith("#")
                and reads_global(_unquoted(stripped.removeprefix("- ")))
            ):
                found.append(index + 1)
            index += 1
    return found


def global_read_lines(text: str, *, yaml_file: bool) -> list[int]:
    """Line numbers of *text* that read ``DEBUG`` or ``VALIDATE``.

    Args:
        text: the content of one role file other than ``meta/services.yml``.
        yaml_file: whether *text* is Ansible YAML, whose conditions are
            expressions without Jinja delimiters.
    """
    text = JINJA_COMMENT.sub(lambda comment: "\n" * comment.group(0).count("\n"), text)
    lines = text.splitlines()
    found: set[int] = set()
    for match in JINJA_BLOCK.finditer(text):
        number = text.count("\n", 0, match.start()) + 1
        if lines[number - 1].lstrip().startswith("#"):
            continue
        if reads_global(match.group("expr") or match.group("stmt") or ""):
            found.add(number)
    if yaml_file:
        found.update(_condition_lines(lines))
    return sorted(found)


def _walk(node: object, path: tuple[str, ...]) -> Iterable[tuple[tuple[str, ...], str]]:
    if isinstance(node, Mapping):
        for key, child in node.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _walk(child, (*path, str(index)))
    elif isinstance(node, str):
        yield path, node


def services_global_reads(services: object) -> list[str]:
    """Dotted paths of ``meta/services.yml`` whose value reads a mode global.

    Args:
        services: the file's parsed content.
    """
    return [
        ".".join(path)
        for path, value in _walk(services, ())
        if global_read_lines(value, yaml_file=False)
    ]


def read_switches(
    role: str, has_application_id: bool, texts: Iterable[str]
) -> tuple[set[str], list[str]]:
    """The switches the code of *role* reads, and the reads that break the rule.

    Args:
        role: the role directory name.
        has_application_id: whether the role's ``vars/main.yml`` defines it.
        texts: the content of every scanned file of the role.
    """
    switches: set[str] = set()
    findings: list[str] = []
    for text in texts:
        findings.extend(
            f"{role}: reads the {match.group('switch')} switch through "
            f"lookup('config'), call lookup('{match.group('switch')}') instead"
            for match in CONFIG_READ.finditer(text)
        )
        for match in SWITCH_LOOKUP.finditer(text):
            switch = match.group("switch")
            args = match.group("args").strip()
            literal = LITERAL_ARG.match(args)
            if not args and not has_application_id:
                findings.append(
                    f"{role}: defines no application_id, call "
                    f"lookup('{switch}', '{role}')"
                )
            elif args and not literal:
                findings.append(
                    f"{role}: lookup('{switch}' {args}) names the role through an "
                    f"expression, call lookup('{switch}') or lookup('{switch}', '{role}')"
                )
            elif literal and literal.group("role") != role:
                findings.append(
                    f"{role}: reads the {switch} switch of {literal.group('role')}"
                )
            else:
                switches.add(switch)
    return switches, findings


def declaration_findings(
    role: str, entity: str, services: object, read: set[str]
) -> list[str]:
    """Findings for the overrides *role* declares against the lookups it calls.

    Args:
        role: the role directory name.
        entity: the role's primary entity.
        services: the parsed ``meta/services.yml``.
        read: the switches the role's code reads.
    """
    services = services if isinstance(services, Mapping) else {}
    findings: list[str] = []
    for other, config in services.items():
        if other == entity or not isinstance(config, Mapping):
            continue
        findings.extend(
            f"{role}: declares {other}.{switch}, only the primary entity {entity} carries it"
            for switch in SWITCHES
            if switch in config
        )
    primary = services.get(entity)
    primary = primary if isinstance(primary, Mapping) else {}
    for switch in SWITCHES:
        if switch not in primary:
            continue
        spec = primary[switch]
        if not isinstance(spec, Mapping) or set(spec) != {"enabled"}:
            findings.append(f"{role}: {entity}.{switch} must hold exactly `enabled`")
        if switch not in read:
            findings.append(
                f"{role}: declares {entity}.{switch}, but its code never calls "
                f"lookup('{switch}') (dead config)"
            )
    return findings


def _role_texts() -> dict[str, dict[str, str]]:
    prefix = f"{ROLES_DIR}{os.sep}"
    index: dict[str, dict[str, str]] = {}
    for path in iter_project_files():
        if not path.startswith(prefix):
            continue
        role, _, relative = path[len(prefix) :].partition(os.sep)
        relative = PurePath(relative).as_posix()
        if relative == ROLE_FILE_META_SERVICES or PurePath(relative).suffix == ".md":
            continue
        try:
            index.setdefault(role, {})[relative] = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
    return index


def _services(role_dir) -> object:
    return load_yaml_any(str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={})


def _has_application_id(role_dir) -> bool:
    variables = load_yaml_any(
        str(role_dir / ROLE_FILE_VARS_MAIN), default_if_missing={}
    )
    return isinstance(variables, Mapping) and "application_id" in variables


class TestRoleModeSwitches(unittest.TestCase):
    def test_no_role_reads_a_global_mode(self):
        findings = [
            f"roles/{role}/{relative}:{line}"
            for role, texts in sorted(_role_texts().items())
            for relative, text in sorted(texts.items())
            for line in global_read_lines(
                text, yaml_file=PurePath(relative).suffix in YAML_SUFFIXES
            )
        ]
        findings.extend(
            f"roles/{role_dir.name}/{ROLE_FILE_META_SERVICES}: {path}"
            for role_dir in iter_role_dirs()
            for path in services_global_reads(_services(role_dir))
        )
        self.assertEqual(
            findings,
            [],
            "DEBUG / VALIDATE read inside a role. Call lookup('debug') / "
            "lookup('validate') (lookup('<switch>', '<role>') where the code has no "
            "application_id of its own); a per-role override goes to "
            "services.<entity>.<switch>.enabled in meta/services.yml or the "
            "inventory:\n" + "\n".join(findings),
        )

    def test_switch_reads_go_through_the_lookups_and_overrides_are_read(self):
        texts = _role_texts()
        findings: list[str] = []
        for role_dir in iter_role_dirs():
            role = role_dir.name
            read, read_findings = read_switches(
                role, _has_application_id(role_dir), texts.get(role, {}).values()
            )
            findings.extend(read_findings)
            findings.extend(
                declaration_findings(role, entity_name(role), _services(role_dir), read)
            )
        self.assertEqual(findings, [], "\n".join(findings))


if __name__ == "__main__":
    unittest.main()
