from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from collections.abc import Mapping

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
BUILD = "scripts/github/runner/build_deploy_image.sh"
_DEPLOY = re.compile(r"\bmake\s+compose-deploy\b")


def _run(step: Mapping) -> str:
    return str(step.get("run") or "")


def problems(workflows: Mapping[str, Mapping]) -> list[str]:
    """Return every compose-deploy job that does not build its image first.

    Args:
        workflows: parsed workflow files keyed by file name.

    Returns:
        One ``<file>:<job>`` line per job whose first ``make compose-deploy``
        step has no earlier step running the build script.
    """
    found: list[str] = []
    for name, workflow in sorted(workflows.items()):
        for job_id, job in (workflow.get("jobs") or {}).items():
            steps = job.get("steps") or []
            deploy = next(
                (i for i, step in enumerate(steps) if _DEPLOY.search(_run(step))),
                None,
            )
            if deploy is None:
                continue
            if not any(BUILD in _run(step) for step in steps[:deploy]):
                found.append(f"{name}:{job_id}")
    return found


def _tree() -> dict[str, Mapping]:
    return {
        path.name: load_yaml_any(str(path)) or {}
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }


def _workflow(*runs: str) -> dict:
    return {"jobs": {"deploy": {"steps": [{"run": run} for run in runs]}}}


class TestDeployImageBuiltInJob(unittest.TestCase):
    def test_the_tree_still_has_a_compose_deploy_job(self) -> None:
        deploying = [
            name
            for name, workflow in _tree().items()
            for job in (workflow.get("jobs") or {}).values()
            if any(_DEPLOY.search(_run(step)) for step in job.get("steps") or [])
        ]
        self.assertTrue(deploying)

    def test_every_compose_deploy_job_builds_its_image_first(self) -> None:
        self.assertEqual(
            problems(_tree()),
            [],
            f"these jobs deploy an image no job is ordered to produce; run {BUILD} "
            "before the first make compose-deploy step",
        )

    def test_red_fixture_a_deploy_without_a_build_fails(self) -> None:
        self.assertEqual(
            problems({"w.yml": _workflow("make compose-deploy bundles=agents")}),
            ["w.yml:deploy"],
        )

    def test_red_fixture_a_build_after_the_deploy_fails(self) -> None:
        self.assertEqual(
            problems({"w.yml": _workflow("make compose-deploy", f"bash {BUILD}")}),
            ["w.yml:deploy"],
        )

    def test_green_fixture_a_build_before_the_deploy_passes(self) -> None:
        self.assertEqual(
            problems({"w.yml": _workflow(f"bash {BUILD}", "make compose-deploy")}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
