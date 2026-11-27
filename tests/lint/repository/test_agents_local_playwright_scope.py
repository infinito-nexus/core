from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests.utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-agents-local.yml"
PLAYWRIGHT = PROJECT_ROOT / "roles" / "test-e2e-playwright"
DEFAULTS = PLAYWRIGHT / ROLE_FILE_DEFAULTS_MAIN
FILTER = PLAYWRIGHT / "filter_plugins" / "discover_playwright_roles.py"
JOB = "agents-local"
HOOK = "INIT_VARS_EXTRA"
ONLY = "test_e2e_playwright_only_roles"
SKIP = "test_e2e_playwright_skip_roles"


def skip_roles(workflow: Path) -> object:
    """Args:
        workflow: the agents-local workflow file.

    Returns:
        The value the job's ``INIT_VARS_EXTRA`` gives the skip list, parsed the
        way ``selection.sh`` composes the init vars, or ``None``.
    """
    job = load_yaml_any(str(workflow))["jobs"][JOB]
    fragment = str((job.get("env") or {}).get(HOOK) or "")
    if not fragment:
        return None
    return json.loads(f'{{"RUNTIME": "dev", {fragment}}}').get(SKIP)


def check(workflow: Path = WORKFLOW, defaults: Path = DEFAULTS) -> list[str]:
    """Args:
        workflow: the agents-local workflow file.
        defaults: the Playwright role defaults holding the run list.

    Returns:
        Why the job would still run a spec: its skip list must be the exact
        expression the run list defaults to, so every role the deploy runs is
        skipped.
    """
    expected = load_yaml_any(str(defaults))[ONLY]
    actual = skip_roles(workflow)
    if actual != expected:
        return [f"{workflow.name}: {HOOK} sets {SKIP} to {actual!r}, not {expected!r}"]
    return []


class TestAgentsLocalPlaywrightScope(unittest.TestCase):
    def test_real_tree_passes(self):
        self.assertEqual(check(), [])

    def test_the_skip_list_empties_the_run_list(self):
        spec = importlib.util.spec_from_file_location(
            "discover_playwright_roles", FILTER
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        discover_playwright_roles = module.discover_playwright_roles

        running = ["web-app-hermes", "web-app-agent-fixture", "web-app-keycloak"]
        self.assertEqual(
            discover_playwright_roles(
                str(PROJECT_ROOT), only_roles=running, skip_roles=running
            ),
            [],
        )
        self.assertNotEqual(
            discover_playwright_roles(str(PROJECT_ROOT), only_roles=running), []
        )

    def _workflow(self, tmp: str, value: object) -> Path:
        path = Path(tmp) / WORKFLOW.name
        fragment = json.dumps({SKIP: value})[1:-1]
        path.write_text(
            f"jobs:\n  {JOB}:\n    env:\n      {HOOK}: {json.dumps(fragment)}\n",
            encoding="utf-8",
        )
        return path

    def test_red_fixture_a_partial_skip_list_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotEqual(check(self._workflow(tmp, ["web-app-hermes"])), [])

    def test_red_fixture_no_hook_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / WORKFLOW.name
            path.write_text(f"jobs:\n  {JOB}:\n    env: {{}}\n", encoding="utf-8")
            self.assertNotEqual(check(path), [])


if __name__ == "__main__":
    unittest.main()
