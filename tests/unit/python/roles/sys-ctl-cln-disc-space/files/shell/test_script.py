"""The disc-space cleanup cleans only the pacman cache directories it can write."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "sys-ctl-cln-disc-space" / "files" / "shell" / "script.sh"
)
STUBS = {
    "df": '#!/bin/sh\necho "Use%"\n',
    "find": "#!/bin/sh\nexit 0\n",
    "systemctl": "#!/bin/sh\nexit 1\n",
    "pacman": '#!/bin/sh\nprintf "%s\\n" "$*" >>"${STUB_LOG}"\n',
}


class TestPacmanCleanup(unittest.TestCase):
    def test_a_cache_dir_it_cannot_write_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            writable = Path(tmp) / "shared" / "pacman"
            writable.mkdir(parents=True)
            unwritable = Path(tmp) / "host-pkg-not-writable"
            stubs = {
                **STUBS,
                "pacman-conf": f'#!/bin/sh\nprintf "%s/\\n%s/\\n" "{unwritable}" "{writable}"\n',
            }
            for name, body in stubs.items():
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            for name in ("sed", "yes"):
                (bin_dir / name).symlink_to(shutil.which(name))
            log = Path(tmp) / "pacman.log"
            log.touch()
            done = subprocess.run(
                ["/bin/sh", str(SCRIPT), "90", "--force"],
                env={"PATH": str(bin_dir), "STUB_LOG": str(log)},
                capture_output=True,
                text=True,
                check=False,
            )
            calls = log.read_text().splitlines()  # nocheck: cache-read  stub call log
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(calls, [f"-Sc --cachedir {writable}/"])


if __name__ == "__main__":
    unittest.main()
