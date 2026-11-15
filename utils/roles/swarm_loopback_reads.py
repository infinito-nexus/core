"""Host-side reads of a loopback port that swarm does not publish.

The consumer half of ``utils/roles/swarm_loopback.py``: which variables hold a
loopback endpoint, which lines read one, directly or through such a variable,
and which definition markers answer the reads through a variable.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml

from utils.cache.files import read_text
from utils.roles.swarm_loopback import VHOST_INPUT_NAMES, is_vhost_input
from utils.roles.swarm_loopback_markers import attached_marker

if TYPE_CHECKING:
    from pathlib import Path

LOOPBACK_READ = re.compile(r"ports\.local\.|\bDOCKER_REACH_HOST\b")
_LOOPBACK_HOST = re.compile(
    r"\bDOCKER_REACH_HOST\b|\b127\.0\.0\.1\b|(?<![\w.-])localhost\b"
)
_LOCAL_PORT = re.compile(r"ports\.local\.")
_BARE_HOST = re.compile(
    r"""\s*['"]?(?:\{\{\s*DOCKER_REACH_HOST\s*\}\}|127\.0\.0\.1|localhost)['"]?\s*"""
)
_BARE_LITERAL = re.compile(r"\b127\.0\.0\.1\b(?!:)|(?<![\w.-])localhost\b(?!:)")


def grown(values: dict[str, str], names: set[str]) -> set[str]:
    """Returns *names* and every name whose value references one of them, transitively.

    Args:
        values: variable name, dotted for nested mappings, to its value as text.
        names: the names to grow from.
    """
    while True:
        pattern = names_pattern(names)
        larger = names | {
            name for name, value in values.items() if pattern and pattern.search(value)
        }
        if larger == names:
            return names
        names = larger


def _closure(values: dict[str, str], seed: re.Pattern[str]) -> set[str]:
    return grown(values, {name for name, value in values.items() if seed.search(value)})


def _bare_hosts(values: dict[str, str]) -> set[str]:
    names = {name for name, value in values.items() if _BARE_HOST.fullmatch(value)}
    while names:
        reference = re.compile(
            r"\s*\{\{\s*" + names_pattern(names).pattern + r"\s*\}\}\s*"
        )
        larger = names | {
            name for name, value in values.items() if reference.fullmatch(value)
        }
        if larger == names:
            break
        names = larger
    return names


def blinded(values: dict[str, str], names: set[str]) -> dict[str, str]:
    """Returns *values* without *names*, and with every mention of them removed.

    Args:
        values: variable name, dotted for nested mappings, to its value as text.
        names: the names a definition marker answers.
    """
    pattern = names_pattern(names)
    if pattern is None:
        return dict(values)
    return {
        name: pattern.sub("", value)
        for name, value in values.items()
        if name not in names
    }


def definition_markers(path: Path) -> dict[str, tuple[int, str]]:
    """Returns ``{dotted name: (marker line, reason)}`` of the leaf variables a marker answers.

    The marker sits on the definition's line or in the comment block above it,
    and answers every read through that name and through the names derived
    from it.

    Args:
        path: a YAML vars file (``group_vars/all/*.yml``, ``vars/main.yml``, ``defaults/main.yml``).
    """
    if not path.is_file():
        return {}
    text = read_text(str(path))
    lines = text.splitlines()
    found: dict[str, tuple[int, str]] = {}

    def walk(node: yaml.Node, prefix: str) -> None:
        if not isinstance(node, yaml.MappingNode):
            return
        for key, value in node.value:
            if not isinstance(key, yaml.ScalarNode):
                continue
            name = f"{prefix}.{key.value}" if prefix else str(key.value)
            if isinstance(value, yaml.MappingNode):
                walk(value, name)
                continue
            marker = attached_marker(lines, key.start_mark.line + 1)
            if marker is not None:
                found[name] = marker

    for document in yaml.compose_all(text, Loader=yaml.SafeLoader):
        walk(document, "")
    return found


def loopback_names(values: dict[str, str]) -> set[str]:
    """Returns the names whose value is a loopback endpoint: a loopback host and a local port.

    Both halves may come through other names. A bare local port number, as
    ``LDAP.SERVER.PORT``, is left out, because containers pair it with a
    service name; so are the vhost inputs (``http_port`` and its siblings),
    which openresty hands to ``proxy_pass`` and swarm ignores, and every value
    that hands one to the vhost.

    Args:
        values: variable name, dotted for nested mappings, to its value as text.
    """
    hosts = _closure(values, _LOOPBACK_HOST)
    ports = _closure(values, _LOCAL_PORT)
    return {
        name for name in hosts & ports if not is_vhost_input(values[name])
    } - VHOST_INPUT_NAMES


def names_pattern(names: set[str]) -> re.Pattern[str] | None:
    """Returns the pattern of a mention of any of *names*, or None for none.

    Args:
        names: variable names, dotted for nested mappings.
    """
    if not names:
        return None
    return re.compile(
        r"(?<![\w.])(?:" + "|".join(re.escape(name) for name in sorted(names)) + r")\b"
    )


def flattened(data: object, prefix: str = "") -> dict[str, str]:
    """Returns a mapping's leaves as ``{dotted.path: value as text}``.

    Args:
        data: a loaded YAML mapping.
        prefix: the dotted path of *data* itself.
    """
    if not isinstance(data, dict):
        return {prefix: str(data)} if prefix else {}
    leaves: dict[str, str] = {}
    for key, value in data.items():
        leaves.update(flattened(value, f"{prefix}.{key}" if prefix else str(key)))
    return leaves


def split_patterns(
    values: dict[str, str],
) -> tuple[re.Pattern[str], re.Pattern[str]]:
    """Returns the patterns of a loopback host and of a local port, each literal or through a name.

    A task that names one in one value and the other in another, as
    ``login_host`` beside ``login_port``, reads a loopback endpoint as well.
    Only a bare host counts: a name whose value is nothing but a loopback host
    or another such name, and a literal loopback host that no ``:`` port
    follows, since a host with a port of its own is a complete endpoint.

    Args:
        values: variable name, dotted for nested mappings, to its value as text.
    """
    hosts = names_pattern(_bare_hosts(values))
    ports = names_pattern(
        {
            name
            for name in _closure(values, _LOCAL_PORT)
            if not is_vhost_input(values[name])
        }
        - VHOST_INPUT_NAMES
    )
    return (
        re.compile(_BARE_LITERAL.pattern + (f"|{hosts.pattern}" if hosts else "")),
        re.compile(_LOCAL_PORT.pattern + (f"|{ports.pattern}" if ports else "")),
    )


def read_pattern(names: set[str]) -> re.Pattern[str]:
    """Returns the pattern of a line that reads a loopback port, directly or through *names*.

    Args:
        names: from ``loopback_names``.
    """
    named = names_pattern(names)
    return re.compile(LOOPBACK_READ.pattern + (f"|{named.pattern}" if named else ""))
