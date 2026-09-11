from __future__ import annotations

import math
import re
import unittest

from cli.meta.ci import slots
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

WORKFLOW = PROJECT_ROOT / ".github/workflows/call-orchestrator.yml"


class TestChunkBlocksCoverTheBudget(unittest.TestCase):
    def test_the_declared_block_count_matches_the_orchestrator(self) -> None:
        jobs = load_yaml_any(str(WORKFLOW))["jobs"]
        declared = [
            name for name in jobs if re.fullmatch(r"test-deploy-chunk-\d+", name)
        ]
        self.assertEqual(
            len(declared),
            slots.chunk_blocks(),
            "INFINITO_CI_MAX_CHUNKS must equal the chunk jobs call-orchestrator.yml "
            "declares; a plan larger than the chain silently drops its tail",
        )

    def test_a_short_priority_chunk_strands_no_budget(self) -> None:
        filled = math.ceil(slots.available() / slots.chunk_size())
        self.assertGreaterEqual(
            slots.chunk_blocks(),
            filled + 1,
            "a priority chunk shorter than a block still occupies one, so the "
            "regular rows need a block beyond what the budget fills to spend "
            "the rest of it",
        )


if __name__ == "__main__":
    unittest.main()
