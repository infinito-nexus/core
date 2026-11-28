from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-test.yml"
LINT_WORKFLOW = PROJECT_ROOT / ".github/workflows/call-lint.yml"
MAKEFILE = PROJECT_ROOT / "Makefile"
_DEFAULT_SUITES = re.compile(
    r"^test:.*\n\t@bash scripts/make/parallel\.sh \$\(or \$\(targets\),(?P<suites>[^)]+)\)",
    re.MULTILINE,
)


def make_test_suites() -> list[str]:
    """Returns:
    The targets ``make test`` fans out when no ``targets`` is passed.
    """
    match = _DEFAULT_SUITES.search(read_text(str(MAKEFILE)))
    if match is None:
        return []
    return match.group("suites").split()


def matrix_suites(workflow: dict) -> list[str]:
    """Args:
        workflow: the parsed call-test.yml.

    Returns:
        Every make target the matrix legs pass as ``targets``, in leg order.
    """
    include = workflow["jobs"]["test"]["strategy"]["matrix"]["include"]
    return [target for leg in include for target in leg["targets"].split()]


def step_index(steps: list[dict], needle: str) -> int:
    """Args:
        steps: the steps of one job.
        needle: text the step's ``uses`` or ``run`` contains.

    Returns:
        The index of the first matching step, -1 when none matches.
    """
    for index, step in enumerate(steps):
        if needle in str(step.get("uses", "")) + str(step.get("run", "")):
            return index
    return -1


class TestTestMatrixCoversMakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load_yaml_any(str(WORKFLOW))
        self.steps = self.workflow["jobs"]["test"]["steps"]

    def test_the_legs_run_every_suite_of_make_test_once(self) -> None:
        suites = make_test_suites()
        self.assertNotEqual(suites, [])
        legs = matrix_suites(self.workflow)
        self.assertEqual(sorted(legs), sorted(suites))

    def test_every_leg_reports_even_when_another_fails(self) -> None:
        self.assertIs(self.workflow["jobs"]["test"]["strategy"]["fail-fast"], False)

    def test_the_verdict_fails_when_a_suite_fails(self) -> None:
        verdict = self.workflow["jobs"]["verdict"]
        self.assertEqual(verdict["needs"], "test")
        self.assertIn("!cancelled()", verdict["if"])
        self.assertEqual(
            verdict["steps"][-1]["env"]["SUITES_RESULT"], "${{ needs.test.result }}"
        )
        self.assertIn("= success", verdict["steps"][-1]["run"])

    def test_restored_reports_are_dropped_before_the_summary(self) -> None:
        restore = step_index(self.steps, "actions/cache/restore@")
        suite = step_index(self.steps, "make test targets=")
        drop = step_index(self.steps, "! -newer /tmp/test-started -delete")
        summary = step_index(self.steps, "utils/github/pytest_summary.py")
        save = step_index(self.steps, "actions/cache/save@")
        self.assertTrue(0 <= restore < suite < drop < summary < save)
        self.assertIn("touch /tmp/test-started", self.steps[suite]["run"])

    def test_the_ansible_lint_stamp_is_restored_before_and_saved_after_lint(
        self,
    ) -> None:
        steps = load_yaml_any(str(LINT_WORKFLOW))["jobs"]["lint"]["steps"]
        key = step_index(steps, "ansible_lint_fingerprint all")
        restore = step_index(steps, "actions/cache/restore@")
        lint = step_index(steps, "make lint ")
        save = step_index(steps, "actions/cache/save@")
        self.assertTrue(0 <= key < restore < lint < save)
        self.assertEqual(steps[restore]["with"]["path"], "build/ansible-lint.stamp")
        self.assertIn("cache-hit != 'true'", steps[save]["if"])


if __name__ == "__main__":
    unittest.main()
