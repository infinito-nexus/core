"""Forbid the negated ``DEPLOYMENT_MODE != ...`` gate form; require the
positive ``DEPLOYMENT_MODE == ...``.

``DEPLOYMENT_MODE`` is binary (``swarm`` / ``compose``, see
``group_vars/all/18_swarm.yml``), so ``!= 'swarm'`` is exactly
``== 'compose'`` and ``!= 'compose'`` is exactly ``== 'swarm'``. The
positive form reads clearer at the gate site (``when:`` / ``{% if %}``)
and keeps every gate uniform.

Scope: project ``.yml`` / ``.yaml`` / ``.j2`` files (the gate sites),
tests excluded. The matcher in ``utils/annotations/task_gate.py`` and its
``.py`` test inputs are deliberately out of scope: they must keep
referencing the legacy string to recognise it.

Per-line opt-out: ``# nocheck: deployment-mode-negation`` on the
offending line or the immediately preceding non-empty line; file-level
opt-out via the same marker in the file head.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at, is_suppressed_in_head
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "deployment-mode-negation"
_NEGATION = re.compile(r"DEPLOYMENT_MODE\s*!=")


class TestNoDeploymentModeNegation(unittest.TestCase):
    def test_deployment_mode_uses_positive_comparison(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml", ".j2"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = content.splitlines()
            if is_suppressed_in_head(lines, _RULE):
                continue
            for idx, line in enumerate(lines):
                if not _NEGATION.search(line):
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
                "Found negated `DEPLOYMENT_MODE != ...` gates. DEPLOYMENT_MODE is "
                "binary (swarm / compose), so use the positive form for "
                "readability: `DEPLOYMENT_MODE == 'compose'` instead of "
                "`!= 'swarm'` (and `== 'swarm'` instead of `!= 'compose'`).\n\n"
                "Mark with `# nocheck: deployment-mode-negation` only when the "
                "negation is genuinely required.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
