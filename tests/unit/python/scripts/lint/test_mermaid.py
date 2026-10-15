"""``scripts/lint/mermaid.sh`` renders with the browser install-lint provisioned.

``make lint`` runs its targets in parallel, so the script must not reach for a
package manager, and a browser that cannot start must fail the lint once with
its reason instead of once per Markdown file.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = Path(PROJECT_ROOT) / "scripts" / "lint" / "mermaid.sh"
LIBRARY_ERROR = (
    "chrome-headless-shell: error while loading shared libraries: libnspr4.so"
)
RECORDING_STUB = '#!/bin/sh\necho "$(basename "$0")" >> "$STUB_CALLS"\n'


class TestMermaidLint(unittest.TestCase):
    def test_a_browser_that_cannot_start_fails_before_any_file_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            calls = bin_dir / "calls"
            calls.touch()
            for name in ("npx", "apt-get"):
                (bin_dir / name).write_text(RECORDING_STUB)
            (bin_dir / "mmdc").write_text(
                f"{RECORDING_STUB}echo '{LIBRARY_ERROR}' >&2\nexit 1\n"
            )
            for stub in bin_dir.iterdir():
                stub.chmod(0o755)
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("INFINITO_") and k != "BASH_ENV"
            }
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_CALLS"] = str(calls)
            proc = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            recorded = calls.read_text().split()  # nocheck: cache-read  stub call log

        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("cannot render a minimal diagram", proc.stderr)
        self.assertIn(LIBRARY_ERROR, proc.stderr)
        self.assertNotIn("❌", proc.stdout)
        self.assertEqual(recorded, ["mmdc"])


if __name__ == "__main__":
    unittest.main()
