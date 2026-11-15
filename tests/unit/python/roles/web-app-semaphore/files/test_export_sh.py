from __future__ import annotations

import subprocess
import unittest

from ._semaphore_fake import SCRIPTS_DIR

WRAPPER = SCRIPTS_DIR / "export.sh"
PLANTED_RECIPIENT = "age1" + "p" * 58


class TestExportWrapper(unittest.TestCase):
    def test_the_wrapper_refuses_arguments(self) -> None:
        completed = subprocess.run(
            ["bash", str(WRAPPER), PLANTED_RECIPIENT],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("usage: export.sh", completed.stderr)


if __name__ == "__main__":
    unittest.main()
