"""Flag ``profiles:`` blocks in ``compose.yml.j2`` templates when the
block is NOT inside a ``{% if DEPLOYMENT_MODE == 'compose' %}`` (or
equivalent compose-only) Jinja gate.

``docker stack deploy`` silently ignores ``profiles:`` — a
profile-gated service that is supposed to be a one-shot bootstrap (and
is normally inert until explicitly invoked via
``docker compose run --profile X``) then deploys as a regular replicated
swarm service. Without a swarm-only branch this causes the bootstrap
to restart in a loop instead of running once on demand.

Per-line opt-out: ``# nocheck: compose-profiles-without-swarm-gate``
on the offending line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "compose-profiles-without-swarm-gate"

_PROFILES = re.compile(r"^\s*profiles:\s*$")
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


class TestComposeTemplateNoUnguardedProfiles(unittest.TestCase):
    def test_no_unguarded_profiles_in_compose_template(self) -> None:
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
                if not _PROFILES.match(line):
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
                "Found `profiles:` blocks in compose.yml.j2 templates "
                "without a compose-only gate. swarm silently ignores "
                "profiles, so a profile-gated one-shot bootstrap deploys "
                "as a regular replicated service and restart-loops.\n\n"
                "Fix: wrap in `{% if DEPLOYMENT_MODE == 'compose' %}` and "
                "adjust the swarm path so the bootstrap is either deployed "
                "as a true one-shot (restart_policy: condition: none) or "
                "tail-its-logs-driven. Mark with "
                "`# nocheck: compose-profiles-without-swarm-gate` only when "
                "the role is intentionally compose-only.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
