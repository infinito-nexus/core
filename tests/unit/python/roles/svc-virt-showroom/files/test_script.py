import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/svc-virt-showroom/files/shell/script.sh"

IPTABLES_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$STUB_CALLS"
case "$1" in
\t-n) [ "$STUB_CHAIN" = "yes" ] ;;
\t-C) [ "$STUB_PRESENT" = "yes" ] ;;
\t*) exit 0 ;;
esac
"""

FORWARD_OUT = "-o showroombr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT"
FORWARD_IN = "-i showroombr0 -j ACCEPT"


class TestDockerUserScript(unittest.TestCase):
    def run_script(self, *, chain, present):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            stub = bin_dir / "iptables"
            stub.write_text(IPTABLES_STUB)
            stub.chmod(0o755)
            calls = Path(tmp) / "calls"
            calls.touch()
            proc = subprocess.run(
                ["bash", str(SCRIPT), "showroombr0"],
                check=False,
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}:{os.environ['PATH']}",
                    "STUB_CALLS": str(calls),
                    "STUB_CHAIN": chain,
                    "STUB_PRESENT": present,
                },
                capture_output=True,
                text=True,
            )
            logged = calls.read_text()  # nocheck: cache-read stub log written per run
            return proc, logged.splitlines()

    def inserts(self, calls):
        return [call for call in calls if call.startswith("-I ")]

    def test_a_host_without_docker_gets_no_rule(self):
        proc, calls = self.run_script(chain="no", present="no")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual([], self.inserts(calls))

    def test_missing_rules_are_inserted_for_both_directions(self):
        proc, calls = self.run_script(chain="yes", present="no")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(
            [f"-I DOCKER-USER {FORWARD_OUT}", f"-I DOCKER-USER {FORWARD_IN}"],
            self.inserts(calls),
        )

    def test_present_rules_are_not_inserted_twice(self):
        proc, calls = self.run_script(chain="yes", present="yes")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual([], self.inserts(calls))
        self.assertIn(f"-C DOCKER-USER {FORWARD_IN}", calls)


if __name__ == "__main__":
    unittest.main()
