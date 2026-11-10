from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.symbol_glossary import keycap, to_emoji

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
_STARRED = "needs.validate-selection.outputs.starred"


def _star(index: int) -> str:
    return f"${{{{ {_STARRED} > {index} && ' {to_emoji('priority')}' || '' }}}}"


def _load(workflow: str) -> dict:
    return load_yaml_any(str(WORKFLOWS / workflow))


class TestBatchJobNames(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = _load("call-orchestrator.yml")["jobs"]
        self.batches = {
            int(name.rsplit("-", 1)[1]): body
            for name, body in self.jobs.items()
            if re.fullmatch(r"test-deploy-chunk-\d+", name)
        }

    def test_the_orchestrator_still_has_batches(self) -> None:
        self.assertGreater(len(self.batches), 1)

    def test_a_batch_is_named_by_its_keycap_and_starred_by_its_index(self) -> None:
        for index, body in sorted(self.batches.items()):
            with self.subTest(batch=index):
                self.assertEqual(body["name"], f"{keycap(index)} Batch{_star(index)}")

    def test_a_batch_hands_its_star_to_its_discover_job(self) -> None:
        for index, body in sorted(self.batches.items()):
            with self.subTest(batch=index):
                self.assertEqual(body["with"]["index"], str(index))
                self.assertEqual(body["with"]["marker"], _star(index))

    def test_the_star_reads_an_output_the_selection_job_exposes(self) -> None:
        validation = _load("call-validation.yml")
        triggers = validation.get("on") or validation.get(True)
        self.assertIn("starred", triggers["workflow_call"]["outputs"])
        self.assertEqual(
            self.jobs["validate-selection"]["uses"],
            "./.github/workflows/call-validation.yml",
        )
        for index, body in sorted(self.batches.items()):
            with self.subTest(batch=index):
                self.assertIn("validate-selection", body["needs"])


if __name__ == "__main__":
    unittest.main()
