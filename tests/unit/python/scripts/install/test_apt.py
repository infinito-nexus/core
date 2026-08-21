"""The apt wrapper must not reach the network for packages already present.

Runs 32265854076 and 32265543004 lost 40 deploy jobs to a single step: the
Azure Ubuntu mirror stalled, `apt-get update` burned the 10m timeout and exited
124, although the only requested package (jq) ships with the runner image.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

APT = PROJECT_ROOT / "scripts" / "install" / "apt.sh"

DPKG_QUERY_STUB = """#!/usr/bin/env bash
for arg in "$@"; do
	case "${arg}" in
	-*) continue ;;
	esac
	grep -qx "${arg}" "${STUB_INSTALLED}" || exit 1
	printf installed
done
"""

SUDO_STUB = """#!/usr/bin/env bash
exec "$@"
"""

APT_GET_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"${STUB_APT_CALLS}"
"""


def _stub(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run(installed: list[str], packages: list[str]) -> tuple[int, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp)
        _stub(bin_dir, "dpkg-query", DPKG_QUERY_STUB)
        _stub(bin_dir, "sudo", SUDO_STUB)
        _stub(bin_dir, "apt-get", APT_GET_STUB)

        installed_file = bin_dir / "installed.txt"
        installed_file.write_text("".join(f"{name}\n" for name in installed))
        calls_file = bin_dir / "calls.txt"
        calls_file.touch()

        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ['PATH']}",
            STUB_INSTALLED=str(installed_file),
            STUB_APT_CALLS=str(calls_file),
        )
        proc = subprocess.run(
            ["bash", str(APT), *packages],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        text = calls_file.read_text()  # nocheck: cache-read - stub writes it per run
        return proc.returncode, text.splitlines()


class AptShortCircuitTests(unittest.TestCase):
    def test_a_present_package_skips_apt_entirely(self):
        code, calls = _run(installed=["jq"], packages=["jq"])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_a_missing_package_still_updates_and_installs(self):
        code, calls = _run(installed=[], packages=["jq"])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].endswith("update"))
        self.assertTrue(calls[1].endswith("install -y jq"))

    def test_a_partial_hit_installs_only_what_is_missing(self):
        code, calls = _run(installed=["jq"], packages=["jq", "gettext-base"])
        self.assertEqual(code, 0)
        self.assertTrue(calls[1].endswith("install -y gettext-base"))

    def test_no_package_argument_is_rejected(self):
        code, calls = _run(installed=[], packages=[])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
