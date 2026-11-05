from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
BUILD_WORKFLOW = WORKFLOWS / "call-images-build-ci.yml"
DEPLOY_WORKFLOW = WORKFLOWS / "call-test-deploy.yml"
BUILD_JOB = "build"
ACT_GATE = "${{ !env.ACT }}"
MOUNT = "mount_spare_disk.sh"
RELOCATE = "relocate_docker_dataroot.sh"
PRUNE = "docker image prune --all --force"
DUMP = "dump_state.sh"
SWAP = "enlarge_swap.sh"
DOCKER_WRITERS = ("pull_with_retry.sh", "docker/setup-buildx-action", "push_all.sh")
GUARDED_BUILD = (
    "./scripts/github/runner/disk/guard.sh / 6 10 -- ./scripts/image/push_all.sh"
)


def build_steps() -> list[dict]:
    """Steps of the image build job.

    Returns:
        The step mappings of the build job in call-images-build-ci.yml.
    """
    return load_yaml(str(BUILD_WORKFLOW))["jobs"][BUILD_JOB]["steps"]


def deploy_steps() -> list[dict]:
    """Steps of the deploy job that carries the #1330 spare-disk layout.

    Returns:
        The step mappings of the first call-test-deploy.yml job running MOUNT.
    """
    return next(
        job["steps"]
        for job in load_yaml(str(DEPLOY_WORKFLOW))["jobs"].values()
        if any(MOUNT in str(step.get("run", "")) for step in job.get("steps", []))
    )


def position(steps: list[dict], needle: str) -> int:
    """Index of the first step whose run or uses names needle.

    Args:
        steps: step mappings of one job.
        needle: substring of the step's run command or uses reference.

    Returns:
        The index; fails the calling test when no step matches.
    """
    for index, step in enumerate(steps):
        if needle in str(step.get("run", "")) or needle in str(step.get("uses", "")):
            return index
    raise AssertionError(f"no step runs or uses '{needle}'")


class TestImagesBuildDiskLayout(unittest.TestCase):
    def test_build_job_runs_the_deploy_jobs_spare_disk_layout(self) -> None:
        build = build_steps()
        deploy = deploy_steps()
        for script in (MOUNT, RELOCATE):
            with self.subTest(script=script):
                ours = build[position(build, script)]
                theirs = deploy[position(deploy, script)]
                self.assertEqual(ours["run"], theirs["run"])
                self.assertEqual(ours.get("if"), ACT_GATE)

    def test_layout_moves_docker_before_anything_writes_to_it(self) -> None:
        steps = build_steps()
        prune = position(steps, PRUNE)
        mount = position(steps, MOUNT)
        relocate = position(steps, RELOCATE)
        self.assertEqual(steps[prune].get("if"), ACT_GATE)
        self.assertLess(prune, relocate)
        self.assertLess(mount, relocate)
        for writer in DOCKER_WRITERS:
            with self.subTest(writer=writer):
                self.assertLess(relocate, position(steps, writer))

    def test_build_runs_under_the_disk_guard(self) -> None:
        steps = build_steps()
        build = steps[position(steps, "push_all.sh")]
        self.assertEqual(build["run"], GUARDED_BUILD)

    def test_runner_state_is_dumped_right_after_the_layout(self) -> None:
        steps = build_steps()
        relocate = position(steps, RELOCATE)
        self.assertIn(DUMP, str(steps[relocate + 1].get("run", "")))
        self.assertEqual(steps[relocate + 1].get("if"), ACT_GATE)

    def test_deploy_jobs_dump_the_state_a_declined_relocation_left(self) -> None:
        steps = deploy_steps()
        relocate = position(steps, RELOCATE)
        self.assertIn(SWAP, str(steps[relocate + 1].get("run", "")))
        self.assertEqual(steps[relocate + 1].get("if"), ACT_GATE)

    def test_pressure_reports_survive_a_failed_build(self) -> None:
        steps = build_steps()
        build = position(steps, "push_all.sh")
        post = position(steps, "disk/pressure_report.sh POST-BUILD")
        self.assertLess(build, post)
        self.assertEqual(steps[post].get("if"), "always()")


if __name__ == "__main__":
    unittest.main()
