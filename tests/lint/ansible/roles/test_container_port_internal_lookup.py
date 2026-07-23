"""Enforce that ``container_port`` is set from the internal-port config lookup.

Every ``container_port`` assignment (in a ``.j2`` or ``.yml`` role file) must
read the service's internal port via
``lookup('config', application_id, 'services.' ~ service_name ~ '.ports.internal.<name>')``
or reference a constant built that way. Hardcoded literals and the
``.ports.local.`` (host-published) port are rejected: ``container_port`` is the
port the container itself listens on, which is the ``ports.internal`` value.

Suppress with ``# nocheck: container-port-internal-lookup`` on the line or the
line above.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-port-internal-lookup"

_JINJA_SET = re.compile(r"{%-?\s*set\s+container_port\s*=\s*(?P<rhs>.+?)\s*-?%}")
_YAML_ASSIGN = re.compile(r"^\s*container_port:\s*(?P<rhs>.+?)\s*$")

_INTERNAL_LOOKUP = re.compile(r"lookup\(\s*['\"]config['\"].*\.ports\.internal\.")
_ANY_LOOKUP = re.compile(r"lookup\(")
_NUMERIC = re.compile(r"^[\"']?\d+[\"']?$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*[A-Za-z0-9_]+)*$")


def _inner(rhs: str) -> str:
    rhs = rhs.strip()
    if len(rhs) >= 2 and rhs[0] in "\"'" and rhs[-1] == rhs[0]:
        rhs = rhs[1:-1].strip()
    wrapped = re.fullmatch(r"{{-?\s*(?P<expr>.*?)\s*-?}}", rhs)
    if wrapped:
        rhs = wrapped.group("expr").strip()
    return rhs


def _is_valid(rhs: str) -> bool:
    inner = _inner(rhs)
    if not inner:
        return True
    if inner.split("|", 1)[0].strip() == "container_port":
        return True
    if _INTERNAL_LOOKUP.search(inner):
        return True
    if _ANY_LOOKUP.search(inner):
        return False
    if _NUMERIC.match(inner):
        return False
    if _IDENTIFIER.match(inner):
        return True
    return True


def _scan(
    rel_path: str, lines: list[str], findings: list[tuple[str, int, str]]
) -> None:
    for idx, line in enumerate(lines):
        rhs_values = [m.group("rhs") for m in _JINJA_SET.finditer(line)]
        yaml_match = _YAML_ASSIGN.match(line)
        if yaml_match:
            rhs_values.append(yaml_match.group("rhs"))
        for rhs in rhs_values:
            if _is_valid(rhs):
                continue
            line_no = idx + 1
            if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                continue
            findings.append((rel_path, line_no, line.strip()))


class TestContainerPortInternalLookup(unittest.TestCase):
    def test_container_port_uses_internal_config_lookup(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2", ".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith("roles/"):
                continue
            _scan(rel, content.splitlines(), findings)

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(set(findings))
            )
            self.fail(
                "`container_port` must be set from the service's internal port, "
                "not a literal or the host-published `ports.local`:\n"
                "  lookup('config', application_id, "
                "'services.' ~ service_name ~ '.ports.internal.<name>')\n"
                "or a constant built that way.\n\n"
                "Fix: define the port under `services.<svc>.ports.internal.<name>` "
                "in the role config and reference it via the lookup, or use a "
                "constant that does.\n"
                "Or add `# nocheck: container-port-internal-lookup` on the line or "
                "the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
