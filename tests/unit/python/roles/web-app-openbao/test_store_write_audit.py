from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml_any

from .test_audit_device import FAKE_CONTAINER, ROLE_DIR, hashed, jinja_env, role_vars

PROBE_PATH = "ws-audit-probe/1730000000-4242"
PROBE_VALUE = "store-audit-0123456789abcdef0123456789abcdef"
FAKE_BAO = """#!/bin/sh
printf '%s\\n' "$*" >>"$BAO_FAKE_CALLS"
case "$*" in
  *"-format=json -f auth/approle/role/store/secret-id"*)
    printf '{\\n  "data": {\\n    "secret_id": "sid-1",\\n    "secret_id_accessor": "acc-1"\\n  }\\n}\\n' ;;
  *"auth/approle/role/store/role-id"*) printf 'rid-1' ;;
  *"auth/approle/login"*) cat >"$BAO_FAKE_STDIN"; printf 'store-token' ;;
esac
"""


def tasks() -> list[dict[str, Any]]:
    return load_yaml_any(str(ROLE_DIR / "tasks/07_workspaces.yml"))


def check_task(register: str) -> dict[str, Any]:
    return next(task for task in tasks() if task.get("register") == register)


def audit_line(**overrides: Any) -> str:
    """
    Args:
        overrides: replacements of the entry's ``auth`` or ``request`` objects.

    Returns:
        One audit response entry of the probe write, as OpenBao writes it.
    """
    entry = {
        "time": "2026-11-14T10:00:00.123456Z",
        "type": "response",
        "auth": {
            "display_name": "approle",
            "policies": ["store"],
            "metadata": {"role_name": role_vars()["OPENBAO_STORE_APPROLE"]},
        },
        "request": {
            "operation": "create",
            "path": f"{role_vars()['OPENBAO_TENANT_MOUNT']}/data/{PROBE_PATH}",
            "data": {"data": {"value": hashed(PROBE_VALUE)}},
        },
        **overrides,
    }
    return json.dumps(entry, separators=(",", ":"))


def run_check(register: str, log_lines: list[str]) -> dict[str, Any]:
    """
    Args:
        register: the registered name of the check.
        log_lines: the lines ``container logs`` prints.

    Returns:
        What the check registers, ``stdout`` and ``rc``.
    """
    values = role_vars()
    command = (
        jinja_env()
        .from_string(check_task(register)["ansible.builtin.shell"])
        .render(
            OPENBAO_LOCAL_CID="openbao-cid",
            OPENBAO_TENANT_MOUNT=values["OPENBAO_TENANT_MOUNT"],
            OPENBAO_STORE_APPROLE=values["OPENBAO_STORE_APPROLE"],
            openbao_store_audit_probe={"stdout": f"{PROBE_PATH} {PROBE_VALUE}\n"},
        )
    )
    with tempfile.TemporaryDirectory() as scratch:
        container = Path(scratch, "container")
        container.write_text(FAKE_CONTAINER, encoding="utf-8")
        container.chmod(0o755)
        log = Path(scratch, "container.log")
        log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        completed = subprocess.run(
            ["sh", "-c", command],
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PATH": f"{scratch}{os.pathsep}{os.environ['PATH']}",
                "OPENBAO_FAKE_LOG": str(log),
            },
            text=True,
            timeout=30,
        )
    return {"stdout": completed.stdout, "rc": completed.returncode}


def fails(register: str, result: dict[str, Any]) -> bool:
    expression = jinja_env().compile_expression(check_task(register)["failed_when"])
    return bool(expression(**{register: result}))


class TestTheStoreWriteIsAudited(unittest.TestCase):
    def test_one_store_write_under_the_store_role_passes(self) -> None:
        result = run_check("openbao_store_audit_entries", [audit_line()])
        self.assertFalse(fails("openbao_store_audit_entries", result))

    def test_control_a_missing_write_fails(self) -> None:
        result = run_check("openbao_store_audit_entries", ['{"@message":"unsealed"}'])
        self.assertTrue(fails("openbao_store_audit_entries", result))

    def test_control_a_doubled_write_fails(self) -> None:
        result = run_check("openbao_store_audit_entries", [audit_line(), audit_line()])
        self.assertTrue(fails("openbao_store_audit_entries", result))

    def test_control_a_write_of_another_role_fails(self) -> None:
        auth = {"display_name": "approle", "metadata": {"role_name": "ansible"}}
        result = run_check("openbao_store_audit_entries", [audit_line(auth=auth)])
        self.assertTrue(fails("openbao_store_audit_entries", result))

    def test_control_a_read_instead_of_a_write_fails(self) -> None:
        request = {
            "operation": "read",
            "path": f"{role_vars()['OPENBAO_TENANT_MOUNT']}/data/{PROBE_PATH}",
        }
        result = run_check("openbao_store_audit_entries", [audit_line(request=request)])
        self.assertTrue(fails("openbao_store_audit_entries", result))


class TestTheStoreWriteLeaksNoValue(unittest.TestCase):
    def test_a_log_with_the_hmac_only_passes(self) -> None:
        result = run_check("openbao_store_audit_leak", [audit_line()])
        self.assertFalse(fails("openbao_store_audit_leak", result))

    def test_control_a_plaintext_value_fails(self) -> None:
        request = {
            "operation": "create",
            "path": f"{role_vars()['OPENBAO_TENANT_MOUNT']}/data/{PROBE_PATH}",
            "data": {"data": {"value": PROBE_VALUE}},
        }
        result = run_check("openbao_store_audit_leak", [audit_line(request=request)])
        self.assertTrue(fails("openbao_store_audit_leak", result))


class TestTheProbeScript(unittest.TestCase):
    def run_probe(self) -> tuple[subprocess.CompletedProcess[str], str, str]:
        script = ROLE_DIR / "files/shell/store-audit-probe.sh"
        with tempfile.TemporaryDirectory() as scratch:
            bao = Path(scratch, "bao")
            bao.write_text(FAKE_BAO, encoding="utf-8")
            bao.chmod(0o755)
            calls = Path(scratch, "calls")
            stdin = Path(scratch, "stdin")
            completed = subprocess.run(
                ["sh", str(script), "store", "tenant"],
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "PATH": f"{scratch}{os.pathsep}{os.environ['PATH']}",
                    "BAO_FAKE_CALLS": str(calls),
                    "BAO_FAKE_STDIN": str(stdin),
                },
                text=True,
                timeout=30,
            )
            return (
                completed,
                calls.read_text(encoding="utf-8"),  # nocheck: cache-read tempdir
                stdin.read_text(encoding="utf-8"),  # nocheck: cache-read tempdir
            )

    def test_the_probe_writes_erases_and_prints_path_and_value(self) -> None:
        completed, calls, _ = self.run_probe()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        path, value = completed.stdout.split()
        self.assertTrue(path.startswith("ws-audit-probe/"))
        self.assertIn(f"kv put -mount=tenant {path} value={value}", calls)
        self.assertIn(f"kv metadata delete -mount=tenant {path}", calls)
        self.assertIn("token revoke -self", calls)
        self.assertIn("secret_id_accessor=acc-1", calls)

    def test_the_secret_id_reaches_the_login_on_stdin_only(self) -> None:
        completed, calls, stdin = self.run_probe()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(stdin.strip(), "sid-1")
        self.assertNotIn("sid-1", calls)
        self.assertNotIn("sid-1", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
