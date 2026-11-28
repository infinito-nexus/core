from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    Path(PROJECT_ROOT)
    / "scripts"
    / "tests"
    / "deploy"
    / "local"
    / "utils"
    / "cache-retry.sh"
)
NEXUS_STUB = '_cache_retry_nexus() { echo "nexus $*"; return 1; }'


def _invalidate(pool_runner: str) -> str:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("INFINITO_")
    }
    env["INFINITO_POOL_RUNNER"] = pool_runner
    return subprocess.run(
        [
            "bash",
            "-c",
            f'source "{SCRIPT}"\n{NEXUS_STUB}\n_cache_retry_invalidate_nexus',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class TestInvalidateNexus(unittest.TestCase):
    def test_a_pool_job_skips_the_nexus_it_cannot_reach(self) -> None:
        shown = _invalidate("true")
        self.assertIn("pool job", shown)
        self.assertNotIn("nexus curl", shown)

    def test_a_host_stack_still_invalidates_through_the_infra_runner(self) -> None:
        self.assertIn("nexus curl", _invalidate("false"))


if __name__ == "__main__":
    unittest.main()
