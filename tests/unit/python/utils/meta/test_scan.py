from __future__ import annotations

import subprocess
import sys
import unittest

from utils.cache import PROJECT_ROOT


class TestScanImports(unittest.TestCase):
    def test_importing_the_scan_loads_no_ansible(self):
        loaded = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, utils.meta.scan; print('ansible' in sys.modules)",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual("False", loaded)


if __name__ == "__main__":
    unittest.main()
