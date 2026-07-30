"""Assert the distro sweep's own budget stays below the step timeout that governs it.

``scripts/tests/deploy/distros.sh`` stops gracefully once
``INFINITO_CI_DISTRO_BUDGET_SECONDS`` is spent and reports the remaining
distros as skipped. That governor is only reachable while the budget is
smaller than the ``timeout-minutes`` of the workflow step that invokes the
sweep. Sized above it, GitHub hard-kills the step mid-distro and a partially
covered run turns into a job failure instead.

This is the lower half of the invariant whose upper half lives in
``test_workflow_timeout_headroom.py``.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import iter_project_files_with_content, read_text

from . import PROJECT_ROOT

_SWEEP = "scripts/tests/deploy/distros.sh"
_BUDGET_KEY = "INFINITO_CI_DISTRO_BUDGET_SECONDS"

_PREAMBLE_ALLOWANCE_SECONDS = 600
"""Checkout, dependency install and runner preparation run inside the job but
outside the sweep, and the post-failure diagnostics/upload steps run after it."""

_BUDGET = re.compile(rf"^{_BUDGET_KEY}=(\d+)\s*$", re.MULTILINE)
_STEP_TIMEOUT = re.compile(r"^\s{6,}timeout-minutes:\s*(\d+)\b")
_STEP_BUDGET = re.compile(rf"^\s+{_BUDGET_KEY}:\s*(\d+)\b")
_STEP_START = re.compile(r"^\s{6}- name:")


def _relative(path: str) -> str:
    return str(path).removeprefix(f"{PROJECT_ROOT}/")


def _budget_seconds() -> int:
    match = _BUDGET.search(read_text(str(PROJECT_ROOT / "default.env")))
    if not match:
        raise AssertionError(f"{_BUDGET_KEY} is not declared in default.env")
    return int(match.group(1))


def _sweep_entrypoints() -> set[str]:
    """The sweep plus every script that invokes it, since workflows call wrappers."""
    entries = {_SWEEP}
    for path, content in iter_project_files_with_content(extensions=(".sh",)):
        rel = _relative(path)
        if rel != _SWEEP and _SWEEP in content:
            entries.add(rel)
    return entries


def _governing_steps() -> list[tuple[str, int, int]]:
    """Return (location, cap_seconds, effective_budget) per capped step running the sweep."""
    entries = _sweep_entrypoints()
    fallback = _budget_seconds()
    found: list[tuple[str, int, int]] = []
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        rel = _relative(path)
        if not rel.startswith(".github/workflows/"):
            continue
        timeout: int | None = None
        budget = fallback
        start = 0
        for lineno, line in enumerate(content.splitlines(), 1):
            if _STEP_START.match(line):
                timeout, budget, start = None, fallback, lineno
            match = _STEP_TIMEOUT.match(line)
            if match:
                timeout = int(match.group(1))
            override = _STEP_BUDGET.match(line)
            if override:
                budget = int(override.group(1))
            if timeout is not None and any(entry in line for entry in entries):
                found.append((f"{rel}:{start}", timeout * 60, budget))
    return found


class TestDistroBudgetFitsTimeout(unittest.TestCase):
    def test_budget_stays_below_every_governing_step_timeout(self) -> None:
        steps = _governing_steps()
        self.assertTrue(steps, "no capped workflow step invoking the sweep was found")

        offenders = [
            f"{where}: step timeout {cap}s - allowance "
            f"{_PREAMBLE_ALLOWANCE_SECONDS}s = {cap - _PREAMBLE_ALLOWANCE_SECONDS}s "
            f"< effective {_BUDGET_KEY}={budget}s"
            for where, cap, budget in steps
            if budget > cap - _PREAMBLE_ALLOWANCE_SECONDS
        ]

        if offenders:
            self.fail(
                f"The effective {_BUDGET_KEY} does not fit the step timeout "
                "that governs the distro sweep. GitHub then hard-kills the "
                "step mid-distro before the sweep can stop gracefully, so a "
                "run that simply did not fit all distros is reported as a job "
                "failure. Override the budget on the step (env:) or raise the "
                "cap.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
