"""Fail a role that sets ``container_port`` without using it in its own files.

sys-svc-container's healthcheck templates now derive ``container_port`` from
``services.<service_name>.ports.internal.http``, so a role that only assigns
``container_port`` to feed those shared templates is redundant. Drop the
assignment (the derivation covers it) or, when the role needs a port the
derivation cannot reach (a non-http internal port, or a service whose key
differs from the derivation's service_name), mark the assignment with
``# nocheck: container-port-set-unused``.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-port-set-unused"

_DEF_JINJA = re.compile(r"{%-?\s*set\s+container_port\s*=")
_DEF_YAML = re.compile(r"^\s*container_port\s*:")
_USE = re.compile(r"\bcontainer_port(?!s)\b")


def _role_of(rel: str) -> str | None:
    parts = rel.split("/")
    if rel.startswith("roles/") and len(parts) > 2:
        return parts[1]
    return None


def _is_def(line: str) -> bool:
    return bool(_DEF_JINJA.search(line) or _DEF_YAML.match(line))


class TestContainerPortSetUnused(unittest.TestCase):
    def test_container_port_assignment_is_used(self) -> None:
        definitions: dict[str, list[tuple[str, int, str, list[str]]]] = defaultdict(
            list
        )
        used: set[str] = set()

        for path_str, content in iter_project_files_with_content(
            extensions=(".j2", ".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            role = _role_of(rel)
            if not role:
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if _is_def(line):
                    definitions[role].append((rel, idx + 1, line.strip(), lines))
                    continue
                if _USE.search(line):
                    used.add(role)

        findings: list[tuple[str, int, str]] = []
        for role, defs in definitions.items():
            if role in used:
                continue
            for rel, line_no, text, lines in defs:
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, text))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(set(findings))
            )
            self.fail(
                "These roles set `container_port` but never use it themselves; the "
                "sys-svc-container healthcheck templates now derive it from "
                "`services.<service_name>.ports.internal.http`, so the assignment is "
                "redundant.\n\n"
                "Fix: drop the assignment (the derivation covers the internal http "
                "port), or, if the role needs a port the derivation cannot reach, add "
                "`# nocheck: container-port-set-unused` on the line or the line "
                "above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
