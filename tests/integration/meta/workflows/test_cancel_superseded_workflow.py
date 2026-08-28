import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
SUPERSEDED = WORKFLOWS / "entry-cancel-superseded.yml"
PUSH_ENTRY = WORKFLOWS / "entry-push-latest.yml"
PR_ENTRY = WORKFLOWS / "entry-pr-change-orchestrate.yml"
CANCEL_JOBS = {
    "cancel-branch-runs": "scripts/github/cancel/branch_runs.sh",
    "cancel-pull-request-runs": "scripts/github/cancel/pull_request_runs.sh",
}


def load(path):
    return load_yaml_any(str(path), default_if_missing={})


def workflow_files():
    yield from sorted(WORKFLOWS.glob("*.yml"))
    yield from sorted(WORKFLOWS.glob("*.yaml"))


def concurrency_groups(workflow):
    """Every group string a workflow declares, workflow-level and job-level.

    GitHub accepts both a bare string and a mapping, so a test that only
    understands the mapping form goes blind exactly when someone adds the
    other one.
    """
    found = []
    for block in [workflow, *workflow.get("jobs", {}).values()]:
        if not isinstance(block, dict):
            continue
        concurrency = block.get("concurrency")
        if isinstance(concurrency, str):
            found.append(concurrency)
        elif isinstance(concurrency, dict):
            found.append(concurrency.get("group", ""))
    return found


PR_GROUP = load(PR_ENTRY)["concurrency"]["group"]


class TestCancelSupersededWorkflow(unittest.TestCase):
    def setUp(self):
        self.workflow = load(SUPERSEDED)

    def test_declares_no_concurrency_group(self):
        self.assertEqual(
            concurrency_groups(self.workflow),
            [],
            "entry-cancel-superseded.yml frees blocked concurrency groups; a group "
            "of its own would queue it behind the very run it has to cancel",
        )

    def test_push_allowlist_matches_the_group_it_backs_up(self):
        group_members = set()
        for path in workflow_files():
            for group in concurrency_groups(load(path)):
                if "global-ci-" in group and "github.ref_name" in group:
                    group_members.add(f".github/workflows/{path.name}")

        allowlist = {
            line.strip()
            for line in self._env("cancel-branch-runs", "INCLUDE_PATHS").splitlines()
            if line.strip()
        }
        self.assertEqual(
            allowlist,
            group_members,
            "the push allowlist must be exactly the members of the concurrency "
            "group it backs up, otherwise it over- or under-cancels",
        )

    def test_each_job_groups_the_way_its_concurrency_group_is_keyed(self):
        expected = {
            "cancel-branch-runs": ("all", load(PUSH_ENTRY)["concurrency"]["group"]),
            "cancel-pull-request-runs": ("event", PR_GROUP),
        }
        for job, (mode, group) in expected.items():
            keyed_on_event = "github.event_name" in group
            self.assertEqual(
                mode == "event",
                keyed_on_event,
                f"{job}: the grouping must mirror the concurrency group key {group}",
            )
            self.assertEqual(
                self._env(job, "KEEP_NEWEST_PER"),
                mode,
                f"{job} must select by 'not the newest run in the group', not by head "
                "SHA: the payload SHA goes stale while the job waits for a runner, "
                "and a skipped or token push moves the tip without creating a run",
            )

    def test_push_job_mirrors_the_cancel_rule_of_its_group(self):
        gate = load(PUSH_ENTRY)["concurrency"]["cancel-in-progress"]
        inner = gate.removeprefix("${{").removesuffix("}}").strip()
        self.assertEqual(
            self.workflow["jobs"]["cancel-branch-runs"]["if"],
            "${{ github.event_name == 'push' && " + inner + " }}",
            "the fallback mirrors the cancel rule of the group it backs up; a "
            "changed polarity or a dropped event guard must fail here",
        )

    def test_covers_every_trigger_of_the_workflows_it_backs_up(self):
        triggers = self.workflow[True]
        self.assertEqual(
            sorted(triggers["push"]["branches"]),
            sorted(
                branch
                for branch in load(PUSH_ENTRY)[True]["push"]["branches"]
                if branch != "main"
            ),
            "a branch that starts CI but no fallback keeps the deadlock; main is "
            "excluded because runs on main are never cancelled",
        )
        pr_types = set()
        for event, block in load(PR_ENTRY)[True].items():
            if str(event).startswith("pull_request"):
                pr_types.update(block["types"])
        self.assertEqual(
            set(triggers["pull_request_target"]["types"]),
            pr_types,
            "an event that starts a PR run but no fallback keeps the deadlock",
        )

    def test_pull_request_job_runs_for_pull_request_target_only(self):
        self.assertEqual(
            self.workflow["jobs"]["cancel-pull-request-runs"]["if"],
            "${{ github.event_name == 'pull_request_target' }}",
        )

    def _step(self, job_name):
        run_suffix = CANCEL_JOBS[job_name]
        steps = [
            step
            for step in self.workflow["jobs"][job_name]["steps"]
            if run_suffix in step.get("run", "")
        ]
        self.assertEqual(
            len(steps), 1, f"expected one step running {run_suffix} in job {job_name}"
        )
        return steps[0]

    def _env(self, job_name, key):
        return self._step(job_name)["env"][key]


class TestCancelHelperReferences(unittest.TestCase):
    def test_every_referenced_shell_script_exists(self):
        pattern = re.compile(r"scripts/github/[A-Za-z0-9_./-]+\.sh")
        for path in workflow_files():
            for match in pattern.findall(read_text(str(path))):
                self.assertTrue(
                    (PROJECT_ROOT / match).is_file(),
                    f"{path.name} references missing {match}",
                )

    def test_every_sourced_helper_exists(self):
        pattern = re.compile(r'source "\$\{SCRIPT_DIR\}/([A-Za-z0-9_.-]+)"')
        cancel_dir = PROJECT_ROOT / "scripts" / "github" / "cancel"
        sourced = set()
        for path in sorted(cancel_dir.glob("*.sh")):
            for name in pattern.findall(read_text(str(path))):
                sourced.add(name)
                self.assertTrue(
                    (cancel_dir / name).is_file(),
                    f"{path.name} sources missing {name}",
                )
        self.assertIn("lib.sh", sourced)


if __name__ == "__main__":
    unittest.main()
