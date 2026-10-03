import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-ca-selfsigned/files/shell/with-ca-trust.sh"

TRUST_TOOLS = ("update-ca-certificates", "update-ca-trust", "trust", "certutil")
ANCHOR_WRITERS = ("mkdir", "cp")

PROBE = 'printf "%s\\n" "$SSL_CERT_FILE"; stat -c %a "$SSL_CERT_FILE"'


class TestWithCaTrust(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        for tool in TRUST_TOOLS:
            self._stub(tool, 0)
        for tool in ANCHOR_WRITERS:
            self._stub(tool, 1)
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.ca_cert = self.root / "root-ca.crt"
        self.ca_cert.write_text("ROOT-CA\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _stub(self, name, code):
        stub = self.bin_dir / name
        stub.write_text(f"#!/bin/sh\nexit {code}\n")
        stub.chmod(0o755)

    def run_wrapper(self, **extra_env):
        """Run the wrapper around a probe printing the exported bundle.

        Args:
            extra_env: additional environment variables for the wrapper.

        Returns:
            Tuple of the exported SSL_CERT_FILE path and its octal mode.
        """
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env['PATH']}"
        env["HOME"] = str(self.home)
        env["TMPDIR"] = str(self.tmpdir)
        env["VERBOSE"] = "0"
        env["CA_TRUST_CERT"] = str(self.ca_cert)
        env["CA_TRUST_NAME"] = "infinito.test"
        env.pop("CA_TRUST_BUNDLE", None)
        env.pop("CA_TRUST_CERT_EXTRA", None)
        env.update(extra_env)
        done = subprocess.run(
            ["sh", str(SCRIPT), "sh", "-c", PROBE],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        path, mode = done.stdout.split()
        return path, mode

    def test_readable_bundle_is_used_without_a_temp_file(self):
        bundle = self.root / "ca-bundle.crt"
        bundle.write_text("ROOT-CA\nPUBLIC-CA\n")

        path, _ = self.run_wrapper(CA_TRUST_BUNDLE=str(bundle))

        self.assertEqual(path, str(bundle))
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_extra_cert_bundle_is_world_readable(self):
        bundle = self.root / "ca-bundle.crt"
        bundle.write_text("ROOT-CA\nPUBLIC-CA\n")
        extra = self.root / "extra.crt"
        extra.write_text("EXTRA-CA\n")

        path, mode = self.run_wrapper(
            CA_TRUST_BUNDLE=str(bundle), CA_TRUST_CERT_EXTRA=str(extra)
        )

        self.assertEqual(mode, "644")
        self.assertEqual(
            Path(path).read_text(),  # nocheck: cache-read
            "ROOT-CA\nPUBLIC-CA\nEXTRA-CA\n",
        )

    def test_combined_system_bundle_is_world_readable(self):
        path, mode = self.run_wrapper()

        if path != str(self.ca_cert):
            self.assertEqual(mode, "644")
            combined = Path(path).read_text()  # nocheck: cache-read
            self.assertTrue(combined.endswith("ROOT-CA\n"))


if __name__ == "__main__":
    unittest.main()
