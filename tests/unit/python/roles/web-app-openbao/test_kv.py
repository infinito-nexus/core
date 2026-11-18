from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

KV_TASKS = PROJECT_ROOT / "roles/web-app-openbao/tasks/utils/kv.yml"
FAKE_BAO = """#!/bin/sh
case "$1 $2" in
"write -field=token") cat >/dev/null; echo fake-token ;;
"token revoke") ;;
"kv get") case "$FAKE_KV" in
  held) echo '{"data": {"data": {"token_id": "t-1"}}}' ;;
  missing) echo "No value found at $5" >&2; exit 2 ;;
  sealed) echo "Error making API request. Code: 503. Errors: * Vault is sealed" >&2; exit 2 ;;
  denied) echo "Error making API request. Code: 403. Errors: * permission denied" >&2; exit 2 ;;
  esac ;;
*) exit 97 ;;
esac
"""


def read_script() -> str:
    return next(
        task["vars"]["openbao_kv_script"]
        for task in load_yaml_any(str(KV_TASKS))
        if "openbao-kv read" in task.get("ansible.builtin.shell", {}).get("cmd", "")
    )


class TestKvRead(unittest.TestCase):
    def read(self, answer: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as scratch:
            bao = Path(scratch) / "bao"
            bao.write_text(FAKE_BAO, encoding="utf-8")
            bao.chmod(0o755)
            return subprocess.run(
                ["sh", "-c", read_script(), "openbao-kv", "read", "tenant", "ws/ssh"],
                input='{"role_id": "r", "secret_id": "s"}\n',
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "PATH": f"{scratch}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_KV": answer,
                },
                text=True,
                timeout=60,
            )

    def test_held_key_prints_its_json(self) -> None:
        result = self.read("held")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["data"], {"token_id": "t-1"})

    def test_missing_key_prints_nothing(self) -> None:
        result = self.read("missing")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)

    def test_any_other_read_error_fails_the_read(self) -> None:
        for answer, reason in (
            ("sealed", "Vault is sealed"),
            ("denied", "permission denied"),
        ):
            with self.subTest(answer=answer):
                result = self.read(answer)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(reason, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
