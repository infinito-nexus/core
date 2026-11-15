"""Loopback ports that swarm does not publish, and the code that still needs them.

In swarm ``container_ports`` drops every term that carries ``DOCKER_BIND_HOST``
and resolves ``ports.local``, so nothing listens on that port of the node.
Two lints build on this module: one asks every dropped term how swarm reaches
the service instead, one asks the same of every host-side task that reads a
``ports.local`` port or ``DOCKER_REACH_HOST``, with the read patterns of
``utils/roles/swarm_loopback_reads.py``.

A term needs no answer when the front proxy reaches it (``proxy_pass`` goes
over the overlay in swarm), when it renders only outside swarm, or when it
feeds Discourse's ``expose:`` list. Every other one carries
``nocheck: swarm-loopback-port <category> <reason>``, where the category is
``exec`` (reached through container exec), ``overlay`` (reached by service
name), ``netns`` (reached inside the service's network namespace), ``unused``
(nothing reaches it under swarm) or ``open`` (swarm does not reach it yet; the
reason cites the open criterion that tracks the migration as ``NNN :LINE``,
line ``LINE`` of ``docs/requirements/NNN-*.md``). A task-file marker that
starts with ``file`` before its category covers the whole file and sits in the
file's leading comment block.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

from yaml import YAMLError

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_DOMAINS,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from pathlib import Path

COMPOSE = "compose"
SWARM = "swarm"
_OTHER_MODE = {COMPOSE: SWARM, SWARM: COMPOSE}
_MODE_FLAGS = {"IS_COMPOSE_MODE": COMPOSE, "IS_SWARM_MODE": SWARM}
_FLAG_TERM = re.compile(r"(IS_COMPOSE_MODE|IS_SWARM_MODE)(?:\s*\|\s*bool)?")
_COMPARE_TERM = re.compile(r"compose_mode\s*(==|!=)\s*['\"](compose|swarm)['\"]")
_NOT = re.compile(r"not\s+")
_OR = re.compile(r"\bor\b")
_AND = re.compile(r"\s+and\s+")

_BIND = re.compile(r"\bDOCKER_BIND_HOST\b")
_PAIRS = {"[": "]", "{": "}", "(": ")"}
_CLOSERS = {closer: opener for opener, closer in _PAIRS.items()}
_EXPOSE = re.compile(r"""\bkey\s*=\s*['"]expose['"]""")
_QUOTED = re.compile(r"""^['"]([\w-]+)['"]""")
_ENTITY = re.compile(r"^(?:application_id\s*\|\s*)?entity_name$")
_TAG = re.compile(r"\{%-?\s*(if|elif|else|endif)\b(.*?)-?%\}", re.DOTALL)
_VHOST_INPUT = re.compile(
    r"\b(?:http_port|websocket_port|sso_open_location_http_port|local_port)\b['\"]?\s*[:=]\s*(.+)"
)
_VHOST_KEYS = frozenset(
    {"http_port", "websocket_port", "sso_open_location_http_port", "local_port"}
)
_LOCAL_REF = re.compile(r"services\.([\w-]+)\.ports\.local\.([\w-]+)")
_FOREIGN_LOCAL_REF = re.compile(
    r"lookup\(\s*'config'\s*,\s*'([\w-]+)'\s*,\s*'services\.([\w-]+)\.ports\.local\.([\w-]+)'"
)
_ENTITY_LOCAL_REF = re.compile(
    r"'services\.'\s*~\s*\(?\s*(?:application_id\s*\|\s*)?entity_name\s*\)?\s*~\s*'\.ports\.local\.([\w-]+)'"
)
_NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_FLAVOR_PIN = re.compile(r"'compose'\s+if\s+.*==\s*'([\w-]+)'")


class Term(NamedTuple):
    line: int
    service: str
    protocol: str
    expose: bool


def _opener(text: str, pos: int) -> int:
    depth: dict[str, int] = dict.fromkeys(_PAIRS, 0)
    for index in range(pos - 1, -1, -1):
        char = text[index]
        if char in _CLOSERS:
            depth[_CLOSERS[char]] += 1
        elif char in _PAIRS:
            if depth[char]:
                depth[char] -= 1
            else:
                return index
    return -1


def _closer(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] in _PAIRS:
            depth += 1
        elif text[index] in _CLOSERS:
            depth -= 1
            if not depth:
                return index
    return len(text)


def _split(content: str, separator: str) -> list[str]:
    parts, depth, current = [], 0, []
    for char in content:
        if char in _PAIRS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
        if char == separator and not depth:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return parts


def _in_expose_call(text: str, opener: int) -> bool:
    call = _opener(text, opener)
    while call > 0 and text[call] != "(":
        call = _opener(text, call)
    if call <= 0 or not text[:call].rstrip().endswith("lookup"):
        return False
    return bool(_EXPOSE.search(text[call : _closer(text, call)]))


def bound_terms(text: str) -> list[Term]:
    """Returns every ``container_ports`` term of a template bound to DOCKER_BIND_HOST.

    Args:
        text: the template's text.

    Returns:
        One ``Term`` per ``[service, protocol, DOCKER_BIND_HOST]`` list or
        ``{'ip': DOCKER_BIND_HOST, ...}`` mapping, with the service and the
        protocol as written. A bare ``{{ DOCKER_BIND_HOST }}`` is no term.
    """
    terms: list[Term] = []
    for match in _BIND.finditer(text):
        opener = _opener(text, match.start())
        if opener < 0 or text[opener] == "(":
            continue
        content = text[opener + 1 : _closer(text, opener)]
        parts = _split(content, ",")
        service = protocol = None
        if text[opener] == "[" and len(parts) == 3 and parts[2] == "DOCKER_BIND_HOST":
            service, protocol = parts[0], parts[1]
        elif text[opener] == "{" and text[opener - 1 : opener + 2].count("{") == 1:
            fields = {}
            for part in parts:
                key, _, value = part.partition(":")
                fields[key.strip().strip("'\"")] = value.strip()
            if fields.get("ip") == "DOCKER_BIND_HOST":
                service, protocol = (
                    fields.get("service", ""),
                    fields.get("protocol", ""),
                )
        if service is None:
            continue
        terms.append(
            Term(
                text.count("\n", 0, match.start()) + 1,
                service,
                protocol,
                _in_expose_call(text, opener),
            )
        )
    return terms


def _term_mode(term: str) -> str | None:
    negated = False
    term = term.strip()
    while True:
        if term.startswith("(") and _closer(term, 0) == len(term) - 1:
            term = term[1:-1].strip()
        elif _NOT.match(term):
            negated = not negated
            term = term[_NOT.match(term).end() :].strip()
        else:
            break
    flag = _FLAG_TERM.fullmatch(term)
    compare = _COMPARE_TERM.fullmatch(term)
    if flag:
        mode = _MODE_FLAGS[flag.group(1)]
    elif compare:
        operator, value = compare.groups()
        mode = value if operator == "==" else _OTHER_MODE[value]
    else:
        return None
    return _OTHER_MODE[mode] if negated else mode


def condition_mode(condition: object) -> str | None:
    """Returns the deployment mode a condition confines its code to, or None.

    Only mode variables count: ``IS_COMPOSE_MODE`` and ``IS_SWARM_MODE``,
    optionally piped through ``bool``, and ``compose_mode`` compared with
    ``'compose'`` or ``'swarm'``, each optionally negated with ``not``. A list, as ``when:`` takes it, and a top-level
    ``and`` join conjuncts, and one confining conjunct confines the whole; a
    condition holding ``or`` confines nothing.

    Args:
        condition: a ``when:`` value (string, list or None) or a Jinja ``if`` condition.

    Returns:
        ``COMPOSE`` when the code can run only outside swarm, ``SWARM`` when only
        in swarm, otherwise None.
    """
    if condition is None:
        return None
    conjuncts = condition if isinstance(condition, list) else [condition]
    modes: set[str | None] = set()
    for conjunct in map(str, conjuncts):
        if _OR.search(conjunct):
            return None
        modes.update(_term_mode(term) for term in _AND.split(conjunct))
    modes.discard(None)
    return modes.pop() if len(modes) == 1 else None


def in_compose_branch(text: str, pos: int) -> bool:
    """Whether *pos* sits in a Jinja branch that never renders under swarm.

    An ``if`` or ``elif`` arm is compose-only when its condition confines it to
    compose or an earlier arm of the same chain holds whenever swarm runs; an
    ``else`` arm only in the latter case.

    Args:
        text: the template's text.
        pos: the offset to judge.
    """
    stack: list[dict[str, bool]] = []
    for tag in _TAG.finditer(text, 0, pos):
        kind, condition = tag.group(1), tag.group(2)
        mode = condition_mode(condition) if kind in ("if", "elif") else None
        if kind == "if":
            stack.append({"compose": mode == COMPOSE, "swarm_seen": mode == SWARM})
        elif kind == "elif" and stack:
            frame = stack[-1]
            frame["compose"] = mode == COMPOSE or frame["swarm_seen"]
            frame["swarm_seen"] = frame["swarm_seen"] or mode == SWARM
        elif kind == "else" and stack:
            stack[-1]["compose"] = stack[-1]["swarm_seen"]
        elif kind == "endif" and stack:
            stack.pop()
    return any(frame["compose"] for frame in stack)


def role_variables(role_dir: Path) -> dict[str, str]:
    """Returns the role's ``vars/main.yml`` and ``defaults/main.yml`` values as text.

    Args:
        role_dir: the role directory.
    """
    values: dict[str, str] = {}
    for rel in (ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN):
        data = load_yaml_any(str(role_dir / rel), default_if_missing={}) or {}
        if isinstance(data, dict):
            values.update({str(key): str(value) for key, value in data.items()})
    return values


def compose_pinned(role_dir: Path, rel: str) -> bool:
    """Whether a role file only ever renders under compose.

    A role pins itself with ``compose_mode_force: compose``; web-app-matrix
    pins only its ``ansible`` flavor, so only that flavor's files count.

    Args:
        role_dir: the role directory.
        rel: the file's path relative to the role directory.
    """
    force = role_variables(role_dir).get("compose_mode_force", "").strip()
    if force == "compose":
        return True
    flavor = _FLAVOR_PIN.search(force)
    return bool(flavor) and f"/flavor/{flavor.group(1)}/" in f"/{rel}"


def _expanded(seeds: list[str], variables: dict[str, str]) -> list[str]:
    seen, queue = list(seeds), list(seeds)
    while queue:
        for name in _NAME.findall(queue.pop()):
            value = variables.get(name)
            if value is not None and value not in seen:
                seen.append(value)
                queue.append(value)
    return seen


def _yaml_inputs(data: object) -> list[str]:
    """Returns every string a vhost input key holds anywhere in a parsed YAML node.

    Args:
        data: the parsed node.
    """
    if isinstance(data, list):
        return [found for item in data for found in _yaml_inputs(item)]
    if not isinstance(data, dict):
        return []
    return [
        found
        for key, value in data.items()
        for found in (
            [value]
            if key in _VHOST_KEYS and isinstance(value, str)
            else _yaml_inputs(value)
        )
    ]


def _parsed_inputs(path: Path) -> list[str]:
    """Returns the whole values of a YAML file's vhost inputs, which a wrapped scalar spreads over lines.

    Args:
        path: the YAML file.
    """
    try:
        return _yaml_inputs(load_yaml_any(str(path), default_if_missing={}))
    except (YAMLError, ValueError):
        return []


def vhost_reach(roles_dir: Path) -> dict[str, set[tuple[str, str]]]:
    """Returns, per role, the ``(service, protocol)`` local ports a vhost proxies to.

    The vhost hands them to ``proxy_pass``, which reaches the service over the
    overlay in swarm. A role with ``meta/domains.yml`` proxies to its entity's
    ``http`` port unless told otherwise; every ``http_port``,
    ``websocket_port``, ``sso_open_location_http_port`` and ``local_port=``
    value adds the local ports it reads, through the role's variables. A
    value that reads another role's port, as web-app-litellm reads
    svc-ai-litellm's, credits that role.

    Args:
        roles_dir: the repository's ``roles`` directory.
    """
    reach: dict[str, set[tuple[str, str]]] = {}
    for role_dir in sorted(path for path in roles_dir.iterdir() if path.is_dir()):
        entity = entity_name(role_dir.name)
        own = reach.setdefault(role_dir.name, set())
        if (role_dir / ROLE_FILE_META_DOMAINS).is_file():
            own.add((entity, "http"))
        seeds: list[str] = []
        for path in sorted(role_dir.rglob("*")):
            if path.suffix not in (".yml", ".j2") or not path.is_file():
                continue
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            found = [match.group(1) for match in _VHOST_INPUT.finditer(text)]
            seeds.extend(found)
            if found and path.suffix == ".yml":
                seeds.extend(_parsed_inputs(path))
        for value in _expanded(seeds, role_variables(role_dir)):
            for other, service, protocol in _FOREIGN_LOCAL_REF.findall(value):
                reach.setdefault(other, set()).add((service, protocol))
            own.update(_LOCAL_REF.findall(_FOREIGN_LOCAL_REF.sub("", value)))
            own.update(
                (entity, protocol) for protocol in _ENTITY_LOCAL_REF.findall(value)
            )
    return reach


def candidates(
    expression: str, role_dir: Path, variables: dict[str, str], text: str, pos: int
) -> set[str]:
    """Returns the names a term's service or protocol can take.

    A literal, optionally piped through ``labelled``, is itself; ``entity_name``
    is the role's entity; a name resolves through the template's last
    ``{% set %}`` before *pos*, the role's variables, or every literal the
    template passes to it as a macro keyword. Anything else stays the
    expression, which no reach contains.

    Args:
        expression: the service or protocol as the template writes it.
        role_dir: the role directory.
        variables: the role's variables, from ``role_variables``.
        text: the template's text.
        pos: the term's offset in *text*.
    """
    expression = expression.strip().removeprefix("{{").removesuffix("}}").strip()
    quoted = _QUOTED.match(expression)
    if quoted:
        return {quoted.group(1)}
    if _ENTITY.match(expression):
        return {entity_name(role_dir.name)}
    if not re.fullmatch(r"\w+", expression):
        return {expression}
    sets = re.findall(
        r"\{%-?\s*set\s+" + expression + r"\s*=\s*(.+?)\s*-?%\}", text[:pos]
    )
    if sets:
        return candidates(sets[-1], role_dir, variables, text, pos)
    if expression in variables:
        return candidates(variables[expression], role_dir, {}, text, pos)
    keywords = set(
        re.findall(r"\b" + expression + r"""\s*=\s*['"]([\w-]+)['"]""", text)
    )
    return keywords or {expression}


VHOST_INPUT_NAMES = frozenset(
    {"http_port", "websocket_port", "sso_open_location_http_port"}
)


def is_vhost_input(line: str) -> bool:
    """Whether *line* hands a value to the vhost, which reaches the app over the overlay in swarm.

    Args:
        line: one source line.
    """
    return bool(_VHOST_INPUT.search(line))
