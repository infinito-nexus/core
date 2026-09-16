"""Lint: every host-bound port states whether it answers on the node onion.

A port under ``ports.local`` or ``ports.public`` binds an address on the stack
host, which is what a ``HiddenServicePort`` can forward to. Whether it should be
forwarded is a decision with a cost in both directions: silently off leaves a
service unreachable that the operator believes is on the onion, and silently on
publishes a database, an admin interface or a SOCKS proxy to everyone holding
the onion address. Neither belongs to a default, so the flag is mandatory and
every ``false`` carries the reason it is false.

The flag lives next to the numbers it decides about::

    ports:
      public:
        smtp: 25
        smtps: 465
      onion:
        smtp: true
        smtps: false # nocheck: onion-flag  no implicit-TLS listener when TLS is off

Five groups are out of scope, because for them the answer is architectural
rather than per-role, and a hundred-odd copies of one sentence state it worse
than this paragraph does:

* ``ports.internal`` lives in the container's network namespace, where no
  host-side forward reaches it.
* the categories a hidden service cannot carry, listed and reasoned once in
  ``plugins.lookup.tor_ports.UDP_ONLY_CATEGORIES``.
* ``http``, ``sso`` and ``websocket``, because the node onion already forwards
  port 80 to the reverse proxy, which routes every vhost, every oauth2 hop and
  every socket upgrade behind it. A direct forward there would bypass the proxy,
  its auth and its CSP.
* the implicit-TLS variants, because Tor is already the transport encryption and
  ``container_ports`` drops those listeners entirely when TLS is off, which an
  onion deployment always is.
* an entity declaring ``exposed:``, which is the older opt-in for the same
  decision and is tested per variant. Two flags for one decision is the trap.

A flag naming a category the entity never declares is reported too: it reads as
a live forward and forwards nothing.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: onion-flag`` plus a reason, on or directly above a ``false`` flag.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Mapping

from plugins.lookup.tor_ports import UDP_ONLY_CATEGORIES
from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_role_dirs
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_RULE = "onion-flag"
_HOST_BOUND_SCOPES = ("local", "public")
_PROXY_FRONTED_CATEGORIES = frozenset({"http", "sso", "websocket"})
_IMPLICIT_TLS_CATEGORIES = frozenset({"smtps", "imaps", "pop3s", "ldaps"})
_OUT_OF_SCOPE = (
    UDP_ONLY_CATEGORIES | _PROXY_FRONTED_CATEGORIES | _IMPLICIT_TLS_CATEGORIES
)
_MIN_REASON_CHARS = 10

_MARKER_RE = re.compile(
    r"(?:noqa|nocheck)\s*:\s*"
    r"(?:[a-z0-9][a-z0-9\-]*)(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*(.*)$",
    re.IGNORECASE,
)


def _host_bound_categories(ports: Mapping) -> set[str]:
    """Category names of *ports* that bind a host address as a single TCP port.

    The proxy-fronted categories are skipped under ``local`` and kept under
    ``public``, which is the difference between riding behind the edge proxy and
    being it: 128 roles declare ``http``/``sso``/``websocket`` on the loopback,
    and exactly one publishes ``http`` on the host.
    """
    found: set[str] = set()
    for scope in _HOST_BOUND_SCOPES:
        declared = ports.get(scope)
        if not isinstance(declared, Mapping):
            continue
        skipped = UDP_ONLY_CATEGORIES | _IMPLICIT_TLS_CATEGORIES
        if scope == "local":
            skipped = skipped | _PROXY_FRONTED_CATEGORIES
        found.update(
            category
            for category, value in declared.items()
            if isinstance(value, int)
            and not isinstance(value, bool)
            and category not in skipped
        )
    return found


def _flag_line(lines: list[str], entity: str, category: str) -> int | None:
    """1-based line of ``<category>:`` inside *entity*'s ``onion:`` block."""
    in_entity = False
    onion_indent = -1
    for number, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            in_entity = stripped.startswith(f"{entity}:")
            onion_indent = -1
            continue
        if not in_entity:
            continue
        if onion_indent >= 0 and indent <= onion_indent:
            onion_indent = -1
        if stripped.startswith("onion:"):
            onion_indent = indent
            continue
        if onion_indent >= 0 and stripped.startswith(f"{category}:"):
            return number
    return None


def _reason_for(lines: list[str], line_no: int) -> str | None:
    """The suppression reason governing *line_no*, or None when unsuppressed."""
    candidates = [line_no - 1]
    previous = line_no - 2
    while previous >= 0 and not lines[previous].strip():
        previous -= 1
    candidates.append(previous)
    for index in candidates:
        if index < 0 or not line_has_rule(lines[index], _RULE):
            continue
        match = _MARKER_RE.search(lines[index])
        return match.group(1).strip().lstrip("-:").strip() if match else ""
    return None


class TestOnionPortFlag(unittest.TestCase):
    def test_every_host_bound_port_declares_an_onion_flag(self) -> None:
        findings: list[str] = []
        for role_dir in iter_role_dirs():
            path = role_dir / ROLE_FILE_META_SERVICES
            if not path.is_file():
                continue
            services = load_yaml_any(str(path), default_if_missing={})
            if not isinstance(services, Mapping):
                continue
            lines = read_text(str(path)).splitlines()
            for entity, config in services.items():
                if not isinstance(config, Mapping):
                    continue
                ports = config.get("ports")
                if not isinstance(ports, Mapping) or "exposed" in config:
                    continue
                findings.extend(
                    self._entity_findings(role_dir.name, entity, ports, lines)
                )
        if findings:
            self.fail(
                "Every host-bound port must state whether it answers on the node "
                "onion, via a boolean of the same category name under "
                "`ports.onion`. A `false` flag needs `# nocheck: onion-flag` and "
                "a reason on or above it.\n" + "\n".join(findings)
            )

    def _entity_findings(
        self,
        role: str,
        entity: str,
        ports: Mapping,
        lines: list[str],
    ) -> list[str]:
        declared = _host_bound_categories(ports)
        flags = ports.get("onion")
        flags = flags if isinstance(flags, Mapping) else {}
        where = f"roles/{role}/{ROLE_FILE_META_SERVICES}: {entity}"
        findings = [
            f"{where}.ports.onion.{category}: missing, declare true or false"
            for category in sorted(declared - set(flags))
        ]
        findings.extend(
            f"{where}.ports.onion.{category}: "
            + (
                "out of scope, remove the flag"
                if category in _OUT_OF_SCOPE
                else "no such port is declared under " + " or ".join(_HOST_BOUND_SCOPES)
            )
            for category in sorted(set(flags) - declared)
        )
        for category in sorted(set(flags) & declared):
            findings.extend(
                self._flag_findings(where, entity, category, flags[category], lines)
            )
        return findings

    def _flag_findings(
        self,
        where: str,
        entity: str,
        category: str,
        flag: object,
        lines: list[str],
    ) -> list[str]:
        at = f"{where}.ports.onion.{category}"
        if not isinstance(flag, bool):
            return [f"{at}: must be a literal true or false, not {flag!r}"]
        if flag:
            return []
        line_no = _flag_line(lines, entity, category)
        if line_no is None:
            return [f"{at}: is false but its line could not be located"]
        reason = _reason_for(lines, line_no)
        if reason is None:
            return [
                (
                    f"{at} (line {line_no}): false needs `# nocheck: {_RULE}` and "
                    f"a reason on or above it"
                )
            ]
        if len(reason) < _MIN_REASON_CHARS:
            return [
                (
                    f"{at} (line {line_no}): `# nocheck: {_RULE}` states no reason "
                    f"why the port stays off the onion"
                )
            ]
        return []


if __name__ == "__main__":
    unittest.main()
