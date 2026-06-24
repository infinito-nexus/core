"""Flag ``condition: service_healthy`` (and
``service_completed_successfully``) under ``depends_on:`` in
``compose.yml.j2`` templates when the line is NOT inside a
``{% if DEPLOYMENT_MODE == 'compose' %}`` (or equivalent compose-only)
Jinja gate.

``docker stack deploy`` accepts only the list form of ``depends_on``;
the map form with ``condition: ...`` causes ``Additional property
condition is not allowed`` at deploy time.

Per-line opt-out: ``# nocheck: compose-only-depends-on-condition`` on
the offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-only-depends-on-condition"

_CONDITION = re.compile(
    r"^\s*condition:\s*service_(?:healthy|completed_successfully)\b"
)
_IF = re.compile(r"\{%\s*if\s+(?P<expr>.+?)\s*%\}")
_ELIF = re.compile(r"\{%\s*elif\s+(?P<expr>.+?)\s*%\}")
_ELSE = re.compile(r"\{%\s*else\s*%\}")
_ENDIF = re.compile(r"\{%\s*endif\s*%\}")
_COMPOSE_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*!=\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*==\s*['\"]compose['\"]"
)
_SWARM_ONLY_GATE = re.compile(
    r"DEPLOYMENT_MODE\s*==\s*['\"]swarm['\"]"
    r"|DEPLOYMENT_MODE\s*!=\s*['\"]compose['\"]"
)


def _frame_is_compose_only(expr: str, in_else: bool) -> bool:
    if not in_else:
        return bool(_COMPOSE_ONLY_GATE.search(expr))
    return bool(_SWARM_ONLY_GATE.search(expr))


def _is_inside_compose_only_gate(lines: list[str], target_idx: int) -> bool:
    """Walk lines top-down maintaining a stack of (if-expr, in_else)
    frames and return True if any open gate at target_idx is compose-only."""
    stack: list[tuple[str, bool]] = []
    for i, raw in enumerate(lines):
        if i == target_idx:
            return any(_frame_is_compose_only(e, b) for e, b in stack)
        if _IF.search(raw):
            stack.append((_IF.search(raw).group("expr"), False))
        elif _ELIF.search(raw) and stack:
            stack[-1] = (_ELIF.search(raw).group("expr"), False)
        elif _ELSE.search(raw) and stack:
            stack[-1] = (stack[-1][0], True)
        elif _ENDIF.search(raw) and stack:
            stack.pop()
    return False


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/templates/" in rel_path
        and rel_path.endswith("compose.yml.j2")
    )


class TestComposeTemplateNoUnguardedDependsOnCondition(unittest.TestCase):
    def test_no_unguarded_service_healthy_in_compose_template(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _CONDITION.match(line):
                    continue
                if _is_inside_compose_only_gate(lines, idx):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found `condition: service_healthy` / "
                "`condition: service_completed_successfully` under "
                "`depends_on:` in compose.yml.j2 templates without a "
                "compose-only gate. `docker stack deploy` only accepts the "
                "list form of depends_on and rejects the map form with "
                "conditions.\n\n"
                "Fix: split depends_on per mode. Example:\n\n"
                "    depends_on:\n"
                "    {% if DEPLOYMENT_MODE == 'swarm' %}\n"
                "          - {{ MATOMO_SERVICE }}\n"
                "    {% else %}\n"
                "          {{ MATOMO_SERVICE }}:\n"
                "            condition: service_healthy\n"
                "    {% endif %}\n\n"
                "In swarm the missing healthy-condition has to be replaced by "
                "an explicit ansible-side wait (e.g. tail "
                "`container service logs <stack>_<svc>` for a ready marker, "
                "or poll `container service ps <stack>_<svc> --filter "
                "desired-state=running --format '{{ \"{{.CurrentState}}\" }}'` "
                "until it matches `^Running`).\n\n"
                "Mark with `# nocheck: compose-only-depends-on-condition` only "
                "when the role is intentionally compose-only by design.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
