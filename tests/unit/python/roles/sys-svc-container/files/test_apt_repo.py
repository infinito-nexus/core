import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

SCRIPT = PROJECT_ROOT / "roles/sys-svc-container/files/shell/apt_repo.sh"

CURL_STUB = """#!/bin/sh
dest=""
while [ "$#" -gt 0 ]; do
\tif [ "$1" = "-o" ]; then
\t\tdest="$2"
\t\tshift
\tfi
\tshift
done
if [ -z "$STUB_SERVED_KEY" ]; then
\techo "curl: (7) Failed to connect to download.docker.com port 443 after 0 ms" >&2
\texit 7
fi
cp "$STUB_SERVED_KEY" "$dest"
"""

SUDO_STUB = '#!/bin/sh\nexec "$@"\n'


class TestAptRepoInstallKey(unittest.TestCase):
    def run_install_key(self, *, installed, served):
        """Run `apt_repo.sh install-key` against a stubbed key download.

        Args:
            installed: content of the keyring before the run, or None when no
                key is installed.
            served: content the download returns, or None when the download
                host refuses the connection.

        Returns:
            Tuple of exit code, stdout, stderr and the keyring content after
            the run (None when no keyring exists).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name, body in (("curl", CURL_STUB), ("sudo", SUDO_STUB)):
                stub = bin_dir / name
                stub.write_text(body)
                stub.chmod(0o755)
            keyring_dir = root / "keyrings"
            keyring_dir.mkdir()
            keyring_dir.chmod(0o755)
            key = keyring_dir / "docker.asc"
            if installed is not None:
                key.write_text(installed)
                key.chmod(0o644)
            env = dict(os.environ)
            env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
            env["STUB_SERVED_KEY"] = ""
            if served is not None:
                served_file = root / "served.asc"
                served_file.write_text(served)
                env["STUB_SERVED_KEY"] = str(served_file)
            done = subprocess.run(
                ["bash", str(SCRIPT), "install-key", "debian", str(key)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            after = read_text(str(key)) if key.exists() else None
            return done.returncode, done.stdout, done.stderr, after

    def test_a_refused_download_keeps_the_installed_key(self):
        code, out, err, after = self.run_install_key(installed="OLD KEY\n", served=None)
        self.assertEqual(code, 0, err)
        self.assertIn("changed=0", out)
        self.assertIn("keeping", err)
        self.assertEqual(after, "OLD KEY\n")

    def test_a_refused_download_without_a_key_fails(self):
        code, _, err, after = self.run_install_key(installed=None, served=None)
        self.assertEqual(code, 1)
        self.assertIn("Failed to download the Docker GPG key", err)
        self.assertIsNone(after)

    def test_a_new_key_replaces_the_installed_one(self):
        code, out, err, after = self.run_install_key(
            installed="OLD KEY\n", served="NEW KEY\n"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("changed=1", out)
        self.assertEqual(after, "NEW KEY\n")


if __name__ == "__main__":
    unittest.main()
