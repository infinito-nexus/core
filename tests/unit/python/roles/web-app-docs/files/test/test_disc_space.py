from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from . import PROJECT_ROOT
from .test_mirror import _block

DISC_SPACE = (
    PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "test" / "disc_space.sh"
)
VARS = re.compile(r'--vars ("\{.*\}")')
PLACEHOLDERS = {
    "TLS_MODE": "self_signed",
    "DOMAIN": "example.com",
    "SSH_PUBLIC_KEY": "ssh-ed25519 AAAA docs-guide@infinito",
}


def _inject(block: str, percent: str) -> str:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "block.sh"
        path.write_text(block, encoding="utf-8")
        subprocess.run(
            ["bash", str(DISC_SPACE), str(path)],
            check=True,
            capture_output=True,
            env={"PATH": os.environ["PATH"], "DOCS_TEST_DISC_SPACE_PERCENT": percent},
            text=True,
        )
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read -- disc_space.sh rewrote this tempfile in the same flow


def _provisioned_vars(block: str) -> dict:
    found = VARS.search(block)
    assert found, "the block hands provision no --vars"
    printed = subprocess.run(
        ["bash", "-c", f"printf %s {found.group(1)}"],
        check=True,
        capture_output=True,
        env={"PATH": os.environ["PATH"], **PLACEHOLDERS},
        text=True,
    )
    return json.loads(printed.stdout)


class TestDiscSpace(unittest.TestCase):
    def test_both_shapes_provision_the_stack_limit(self) -> None:
        for is_host in (False, True):
            with self.subTest(is_host=is_host):
                published = _block(is_host=is_host)
                injected = _inject(published, "99")
                provisioned = _provisioned_vars(injected)
                self.assertEqual(provisioned["SIZE_PERCENT_CLEANUP_DISC_SPACE"], 99)
                expected = {
                    **_provisioned_vars(published),
                    "SIZE_PERCENT_CLEANUP_DISC_SPACE": 99,
                }
                self.assertEqual(provisioned, expected)
                subprocess.run(["bash", "-n"], input=injected, check=True, text=True)

    def test_a_limit_that_is_no_whole_percentage_is_a_failure(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            _inject(_block(is_host=False), '99, \\"x\\": 1')

    def test_a_block_without_vars_is_a_failure(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            _inject("echo nothing to provision\n", "99")


if __name__ == "__main__":
    unittest.main()
