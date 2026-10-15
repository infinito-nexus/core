from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "docker" / "cache" / "registry-ca.sh"
NAME = "infinito-registry-cache.crt"
STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$0 $*" >>"${STUB_LOG}"\n'
PKI = "etc/pki/ca-trust/source/anchors"
ARCH = "etc/ca-certificates/trust-source/anchors"
TOOLS = ("bash", "cmp", "dirname", "install")


class TestRegistryCacheCa(unittest.TestCase):
    def fake_root(
        self, tool: str, anchor_dirs: tuple[str, ...], ca: str | None
    ) -> Path:
        """Build a fake root that offers one trust tool.

        Args:
            tool: the trust rebuild command the fake system provides.
            anchor_dirs: anchor directories that already exist in the fake root.
            ca: content of the mounted ``ca.crt``; ``None`` leaves the CA dir unmounted.

        Returns:
            The fake root.
        """
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        if ca is not None:
            (root / "opt" / "registry-cache-ca").mkdir(parents=True)
            (root / "opt" / "registry-cache-ca" / "ca.crt").write_text(
                ca, encoding="utf-8"
            )
        for anchor in anchor_dirs:
            (root / anchor).mkdir(parents=True)
        (root / "bin").mkdir()
        for needed in TOOLS:
            (root / "bin" / needed).symlink_to(shutil.which(needed))
        (root / "bin" / tool).write_text(STUB, encoding="utf-8")
        (root / "bin" / tool).chmod(0o755)
        return root

    def run_script(self, root: Path) -> subprocess.CompletedProcess:
        """Run registry-ca.sh against a fake root.

        Args:
            root: fake root from ``fake_root``.

        Returns:
            The finished process.
        """
        env = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "CA_ROOT")}
        env.update(
            CA_ROOT=str(root),
            PATH=str(root / "bin"),
            STUB_LOG=str(root / "stub.log"),
        )
        return subprocess.run(
            [str(root / "bin" / "bash"), str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def rebuilds(self, root: Path) -> int:
        log = root / "stub.log"
        if not log.exists():
            return 0
        text = log.read_text(encoding="utf-8")  # nocheck: cache-read per-run tempdir
        return len(text.splitlines())

    def test_the_redhat_family_gets_the_pki_anchor(self) -> None:
        root = self.fake_root("update-ca-trust", (PKI,), "CA\n")
        done = self.run_script(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((root / PKI / NAME).is_file())
        self.assertEqual(self.rebuilds(root), 1)

    def test_arch_with_both_anchor_dirs_gets_its_trust_source_anchor(self) -> None:
        root = self.fake_root("update-ca-trust", (PKI, ARCH), "CA\n")
        done = self.run_script(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((root / ARCH / NAME).is_file())

    def test_debian_uses_update_ca_certificates(self) -> None:
        root = self.fake_root("update-ca-certificates", (), "CA\n")
        done = self.run_script(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((root / "usr/local/share/ca-certificates" / NAME).is_file())

    def test_a_second_run_does_not_rebuild(self) -> None:
        root = self.fake_root("update-ca-trust", (ARCH,), "CA\n")
        self.run_script(root)
        done = self.run_script(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.rebuilds(root), 1)

    def test_an_unmounted_ca_dir_is_skipped(self) -> None:
        root = self.fake_root("update-ca-trust", (PKI,), None)
        done = self.run_script(root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.rebuilds(root), 0)

    def test_a_mounted_dir_without_ca_is_refused(self) -> None:
        root = self.fake_root("update-ca-trust", (PKI,), "")
        done = self.run_script(root)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse(any(root.glob(f"**/{NAME}")))


if __name__ == "__main__":
    unittest.main()
