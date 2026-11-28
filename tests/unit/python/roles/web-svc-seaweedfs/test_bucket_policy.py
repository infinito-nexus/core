import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles" / "web-svc-seaweedfs" / "tasks"
UTIL = "utils/bucket/policy.yml"
CORE = "utils/bucket/policies.yml"
PARAMS = {"seaweedfs_bucket_policy_bucket", "seaweedfs_bucket_policy_public"}
EXPORT_BUCKET = "{{ SEAWEEDFS_EXPORT.bucket }}"
EXPORT_GATE = "SEAWEEDFS_EXPORT.enabled | bool"


def includes(tasks, inherited=()):
    """Args:
    tasks: a task list that may hold blocks.
    inherited: the when conditions of the blocks around ``tasks``.

    Returns:
    the policy includes, each with the conditions of its blocks ahead of its own.
    """
    for task in tasks:
        when = task.get("when", [])
        conditions = [*inherited, *(when if isinstance(when, list) else [when])]
        yield from includes(task.get("block", []), conditions)
        if task.get("include_tasks") == UTIL:
            yield {**task, "when": conditions}


def policy_includes(name):
    return list(includes(load_yaml_str(read_text(str(TASKS / name)))))


def export_findings(tasks):
    exports = [
        task
        for task in tasks
        if task.get("vars", {}).get("seaweedfs_bucket_policy_bucket") == EXPORT_BUCKET
    ]
    if len(exports) != 1:
        return [f"{len(exports)} policy includes for the export bucket"]
    findings = []
    if exports[0]["vars"].get("seaweedfs_bucket_policy_public") is not False:
        findings.append("the export bucket is converged as public")
    if EXPORT_GATE not in exports[0].get("when", []):
        findings.append("the export policy runs without the export gate")
    return findings


class TestBucketPolicy(unittest.TestCase):
    def test_every_include_passes_bucket_and_polarity(self):
        for name in (CORE, "01_init_consumer.yml"):
            found = policy_includes(name)
            self.assertTrue(found, name)
            for task in found:
                with self.subTest(file=name, task=task["name"]):
                    self.assertEqual(set(task.get("vars", {})), PARAMS)

    def test_the_core_converges_the_policies_on_the_stack_host(self):
        (task,) = [
            task
            for task in load_yaml_str(read_text(str(TASKS / "00_core.yml")))
            if task.get("include_tasks") == CORE
        ]
        self.assertEqual(task["when"], "IS_STACK_HOST | bool")

    def test_the_export_bucket_keeps_the_anonymous_deny(self):
        self.assertEqual(export_findings(policy_includes(CORE)), [])

    def test_negative_control_an_ungated_export_policy_is_reported(self):
        planted = [
            {**task, "when": [c for c in task["when"] if c != EXPORT_GATE]}
            for task in policy_includes(CORE)
        ]
        self.assertEqual(
            export_findings(planted), ["the export policy runs without the export gate"]
        )

    def test_negative_control_a_public_export_bucket_is_reported(self):
        planted = policy_includes(CORE)
        for task in planted:
            if task["vars"]["seaweedfs_bucket_policy_bucket"] == EXPORT_BUCKET:
                task["vars"]["seaweedfs_bucket_policy_public"] = True
        self.assertEqual(
            export_findings(planted), ["the export bucket is converged as public"]
        )

    def test_negative_control_a_missing_export_policy_is_reported(self):
        planted = [
            task
            for task in policy_includes(CORE)
            if task["vars"]["seaweedfs_bucket_policy_bucket"] != EXPORT_BUCKET
        ]
        self.assertEqual(
            export_findings(planted), ["0 policy includes for the export bucket"]
        )


if __name__ == "__main__":
    unittest.main()
