"""L25: the agents CI workflows exist and are wired. The pull-request
orchestrator calls the local agents workflow, and a nightly cron caller runs
the SaaS agents workflow, so a change to the agent platform is tested on every
pull request and every night. ``make agents-verify`` and ``make
agents-integration`` run those same files through act, and neither file calls
``make agents-verify`` back, which would start act inside act."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from tests.lint.agents import PROJECT_ROOT
from utils.cache.files import read_text

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
SCRIPTS = PROJECT_ROOT / "scripts" / "agents"
LOCAL = "call-test-agents-local.yml"
SAAS = "call-test-agents-saas.yml"
ORCHESTRATOR = "entry-pr-change-orchestrate.yml"
ACT_RUNNERS = {"verify.sh": LOCAL, "integration.sh": SAAS}
_RECURSION = re.compile(r"make\s+agents-verify\b")


def _calls(text: str, workflow: str) -> bool:
    """True when a ``uses:`` line in *text* references *workflow*."""
    return re.search(r"uses:\s*\S*" + re.escape(workflow), text) is not None


def _acts(text: str, workflow: str) -> bool:
    """True when *text* hands *workflow* to act as ``ACT_WORKFLOW``."""
    pattern = r"ACT_WORKFLOW=[\"']?\.github/workflows/" + re.escape(workflow)
    return re.search(pattern, text) is not None


def act_problems(workflows_dir: Path, scripts_dir: Path) -> list[str]:
    """Return why a make target does not run the workflow file the CI runs.

    Args:
        workflows_dir: the .github/workflows directory.
        scripts_dir: the scripts/agents directory of the act wrappers.
    """
    problems: list[str] = []
    for script, workflow in ACT_RUNNERS.items():
        path = scripts_dir / script
        if not path.is_file() or not _acts(read_text(str(path)), workflow):
            problems.append(f"scripts/agents/{script} does not run {workflow} via act")
        called = workflows_dir / workflow
        if called.is_file() and _RECURSION.search(read_text(str(called))):
            problems.append(f"{workflow} calls make agents-verify, act inside act")
    return problems


def check(workflows_dir: Path, scripts_dir: Path = SCRIPTS) -> list[str]:
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

    return problems + act_problems(workflows_dir, scripts_dir)


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

    def test_red_fixture_a_make_target_off_the_ci_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf, scripts = Path(tmp) / "wf", Path(tmp) / "scripts"
            wf.mkdir()
            scripts.mkdir()
            files = {
                wf / LOCAL: "run: make agents-verify mode=compose\n",
                wf / SAAS: "run: python -m cli.agents.scenarios\n",
                scripts / "verify.sh": "make compose-deploy bundles=agents\n",
                scripts / "integration.sh": (
                    f'ACT_WORKFLOW=".github/workflows/{SAAS}" bash act.sh\n'
                ),
            }
            for path, text in files.items():
                path.write_text(text, encoding="utf-8")
            self.assertEqual(
                act_problems(wf, scripts),
                [
                    f"scripts/agents/verify.sh does not run {LOCAL} via act",
                    f"{LOCAL} calls make agents-verify, act inside act",
                ],
            )


if __name__ == "__main__":
    unittest.main()
