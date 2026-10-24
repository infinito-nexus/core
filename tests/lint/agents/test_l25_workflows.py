"""L25: the agents CI workflows exist and are wired. The pull-request
orchestrator calls the local agents workflow, and a nightly cron caller runs
the SaaS agents workflow, so a change to the agent platform is tested on every
pull request and every night."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
LOCAL = "call-test-agents-local.yml"
SAAS = "call-test-agents-saas.yml"
ORCHESTRATOR = "entry-pr-change-orchestrate.yml"


def _calls(text: str, workflow: str) -> bool:
    """True when a ``uses:`` line in *text* references *workflow*."""
    return re.search(r"uses:\s*\S*" + re.escape(workflow), text) is not None


def check(workflows_dir: Path) -> list[str]:
    problems: list[str] = []
    local = workflows_dir / LOCAL
    saas = workflows_dir / SAAS
    orchestrator = workflows_dir / ORCHESTRATOR

    if not local.is_file():
        problems.append(f"{LOCAL} is missing")
    if not saas.is_file():
        problems.append(f"{SAAS} is missing")

    if not orchestrator.is_file():
        problems.append(f"{ORCHESTRATOR} is missing")
    elif not _calls(read_text(str(orchestrator)), LOCAL):
        problems.append(f"{ORCHESTRATOR} does not call {LOCAL}")

    crons = sorted(workflows_dir.glob("cron-*.yml"))
    if not any(_calls(read_text(str(path)), SAAS) for path in crons):
        problems.append(f"no cron-*.yml workflow calls {SAAS}")

    return problems


class TestL25(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(WORKFLOWS), [])

    def test_red_fixture_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp)
            (wf / LOCAL).write_text("on: {workflow_call: {}}\n", encoding="utf-8")
            (wf / SAAS).write_text("on: {workflow_call: {}}\n", encoding="utf-8")
            (wf / ORCHESTRATOR).write_text("jobs: {}\n", encoding="utf-8")
            self.assertNotEqual(check(wf), [])


if __name__ == "__main__":
    unittest.main()
