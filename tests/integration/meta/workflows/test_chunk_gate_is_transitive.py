"""The chunk gate must stop the chain, not just the next chunk.

``chunk_gate`` promises to "stop the chunk chain at its first failed chunk".
A gate that reads only its immediate predecessor cannot keep that promise: a
blocked chunk reports ``skipped``, ``skipped`` is what the gate accepts, and
the chunk after it runs. Exactly one chunk falls out, the rest of the chain
carries on, and the coverage that chunk owned disappears with nothing reporting
it.

Run 33279942812 is the case: chunk 0 red, chunk 1 skipped by the gate, chunk 2
deployed 81 jobs against a chain that was supposed to have stopped.

Every chunk therefore names every chunk before it, in the gate and in ``needs``.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-orchestrator.yml"
JOB = "test-deploy-chunk-{index}"
_RESULT_RE = re.compile(r"needs\.test-deploy-chunk-(\d+)\.result")


def _chunks() -> dict[int, dict]:
    """Return the chunk jobs of the orchestrator, keyed by index."""
    jobs = load_yaml_any(str(WORKFLOW))["jobs"]
    return {
        int(name.rsplit("-", 1)[1]): body
        for name, body in jobs.items()
        if re.fullmatch(r"test-deploy-chunk-\d+", name)
    }


class TestChunkGateIsTransitive(unittest.TestCase):
    def setUp(self) -> None:
        self.chunks = _chunks()

    def test_the_orchestrator_still_has_a_chunk_chain(self) -> None:
        """Without one, every assertion below would pass over nothing."""
        self.assertGreater(len(self.chunks), 1)
        self.assertEqual(sorted(self.chunks), list(range(len(self.chunks))))

    def test_a_gate_reads_every_chunk_before_it(self) -> None:
        for index, body in sorted(self.chunks.items()):
            with self.subTest(chunk=index):
                read = {int(m) for m in _RESULT_RE.findall(body["if"])}
                self.assertEqual(
                    set(range(index)),
                    read,
                    f"chunk {index} gates on {sorted(read)}; a chunk it does not "
                    f"read can fail without stopping it",
                )

    def test_the_finish_job_needs_every_chunk(self) -> None:
        """A chunk it does not need can fail while the pipeline reports green."""
        done = load_yaml_any(str(WORKFLOW))["jobs"]["done"]
        needed = {
            int(name.rsplit("-", 1)[1])
            for name in done["needs"]
            if re.fullmatch(r"test-deploy-chunk-\d+", name)
        }
        self.assertEqual(set(self.chunks), needed)

    def test_a_gate_needs_every_chunk_it_reads(self) -> None:
        """An unneeded job's result is empty, which the gate would let pass."""
        for index, body in sorted(self.chunks.items()):
            with self.subTest(chunk=index):
                read = {int(m) for m in _RESULT_RE.findall(body["if"])}
                needed = {
                    int(name.rsplit("-", 1)[1])
                    for name in body["needs"]
                    if re.fullmatch(r"test-deploy-chunk-\d+", name)
                }
                self.assertTrue(
                    read <= needed,
                    f"chunk {index} reads {sorted(read - needed)} without needing it",
                )


if __name__ == "__main__":
    unittest.main()
