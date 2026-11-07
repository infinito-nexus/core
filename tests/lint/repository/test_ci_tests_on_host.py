"""Lint: the CI test workflow runs ``make test`` on the host.

However the tests run locally, every CI step that runs ``make test`` keeps
``INFINITO_TEST_RUNNER: host``, so a CI test run starts no container. The
effective value is the step's ``env``, else the job's, else the workflow's.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test.yml"
KEY = "INFINITO_TEST_RUNNER"
_MAKE_TEST = re.compile(r"\bmake\s+test(?=\s|$)")


def off_host_steps(workflow: dict) -> list[str]:
    """Args:
        workflow: the parsed workflow.

    Returns:
        One finding per ``make test`` step whose effective runner is not ``host``,
        and one when no step runs ``make test`` at all.
    """
    findings: list[str] = []
    seen = False
    top = workflow.get("env") or {}
    for job_id, job in (workflow.get("jobs") or {}).items():
        job_env = {**top, **(job.get("env") or {})}
        for index, step in enumerate(job.get("steps") or []):
            if not _MAKE_TEST.search(str(step.get("run") or "")):
                continue
            seen = True
            runner = {**job_env, **(step.get("env") or {})}.get(KEY)
            if runner != "host":
                name = step.get("name") or f"step {index}"
                findings.append(f"{job_id}/{name}: {KEY}={runner!r}, expected 'host'")
    if not seen:
        findings.append("no step runs 'make test'")
    return findings


class TestCiTestsOnHost(unittest.TestCase):
    def test_call_test_runs_the_tests_on_the_host(self) -> None:
        workflow = load_yaml_str(read_text(str(WORKFLOW)))
        self.assertEqual(off_host_steps(workflow), [])

    def test_a_docker_runner_is_reported(self) -> None:
        text = read_text(str(WORKFLOW)).replace(f"{KEY}: host", f"{KEY}: docker")
        self.assertNotEqual(off_host_steps(load_yaml_str(text)), [])

    def test_a_step_override_is_reported(self) -> None:
        workflow = load_yaml_str(read_text(str(WORKFLOW)))
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if _MAKE_TEST.search(str(step.get("run") or "")):
                    step["env"] = {KEY: "docker"}
        self.assertNotEqual(off_host_steps(workflow), [])

    def test_a_workflow_without_make_test_is_reported(self) -> None:
        self.assertEqual(
            off_host_steps({"jobs": {"t": {"steps": [{"run": "make test-lint"}]}}}),
            ["no step runs 'make test'"],
        )


if __name__ == "__main__":
    unittest.main()
