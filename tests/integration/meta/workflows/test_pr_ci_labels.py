"""A ``labeled`` run whose jobs all skip still cancels the running pipeline
through its concurrency group and the superseded-run canceller, so every place
that tells CI labels from the rest must carry the same list."""

from __future__ import annotations

import json
import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
PR = WORKFLOWS / "entry-pr-change-orchestrate.yml"
SUPERSEDED = WORKFLOWS / "entry-cancel-superseded.yml"
ORCHESTRATOR = WORKFLOWS / "call-orchestrator.yml"
DEPLOY = WORKFLOWS / "call-test-deploy.yml"
RUN_ALL = "🏃 Run all"
_LIST_RE = re.compile(r"fromJSON\('(\[[^']*\])'\)")
_READ_RE = re.compile(r"labels\.\*\.name, '([^']+)'")


def _labels(expression: str) -> list[str]:
    """Return the label list a ``fromJSON('[...]')`` in *expression* holds."""
    found = _LIST_RE.findall(expression)
    if len(found) != 1:
        raise AssertionError(f"expected one label list in {expression!r}")
    return json.loads(found[0])


def _strings(node: object) -> list[str]:
    """Return every string value of a loaded YAML document."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return []


class TestPrCiLabels(unittest.TestCase):
    def setUp(self) -> None:
        self.pr = load_yaml_any(str(PR))
        self.restart = _labels(self.pr["concurrency"]["group"])

    def test_the_skip_and_the_canceller_use_the_concurrency_list(self) -> None:
        superseded = load_yaml_any(str(SUPERSEDED))
        for where, expression in (
            ("detect-pr-scope", self.pr["jobs"]["detect-pr-scope"]["if"]),
            (
                "cancel-pull-request-runs",
                superseded["jobs"]["cancel-pull-request-runs"]["if"],
            ),
        ):
            with self.subTest(job=where):
                self.assertEqual(_labels(expression), self.restart)

    def test_every_label_the_workflow_reads_restarts_it(self) -> None:
        read = {name for text in _strings(self.pr) for name in _READ_RE.findall(text)}
        self.assertIn(RUN_ALL, read)
        self.assertLessEqual(read, set(self.restart))

    def test_run_all_turns_the_chunk_gate_off(self) -> None:
        chunk_gate = self.pr["jobs"]["ci-orchestrator"]["with"]["chunk_gate"]
        self.assertEqual(
            chunk_gate,
            f"${{{{ !contains(github.event.pull_request.labels.*.name, '{RUN_ALL}') }}}}",
        )

    def test_every_chunk_hands_the_gate_to_its_matrix(self) -> None:
        jobs = load_yaml_any(str(ORCHESTRATOR))["jobs"]
        chunks = {
            name: body
            for name, body in jobs.items()
            if re.fullmatch(r"test-deploy-chunk-\d+", name)
        }
        self.assertGreater(len(chunks), 1)
        for name, body in sorted(chunks.items()):
            with self.subTest(chunk=name):
                self.assertEqual(body["with"]["chunk_gate"], "${{ inputs.chunk_gate }}")
        fail_fast = load_yaml_any(str(DEPLOY))["jobs"]["deploy"]["strategy"][
            "fail-fast"
        ]
        self.assertIn("inputs.chunk_gate", fail_fast)


if __name__ == "__main__":
    unittest.main()
