from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-openbao"
PROBE_VALUE = "probe-1730000000-4242"
HUMAN_POLICIES = ("administrator", "operator", "reader")
AUDIT_STANZA = re.compile(
    r'^audit "(?P<type>[^"]+)" "(?P<path>[^"]+)" \{\n(?P<body>.*?)^\}',
    re.MULTILINE | re.DOTALL,
)
POLICY_PATH = re.compile(
    r'path "(?P<path>[^"]+)" \{\s*capabilities = \[(?P<caps>[^\]]*)\]'
)
FAKE_CONTAINER = '#!/bin/sh\n[ "$1" = logs ] || exit 99\ncat "$OPENBAO_FAKE_LOG"\n'


def role_vars() -> dict[str, Any]:
    return load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))


def jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(ROLE_DIR / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["from_json"] = json.loads
    env.filters["quote"] = shlex.quote
    return env


def audit_stanzas() -> list[re.Match[str]]:
    values = role_vars()
    rendered = (
        jinja_env()
        .get_template("openbao.hcl.j2")
        .render(
            OPENBAO_LOG_LEVEL="info",
            OPENBAO_DATA_DOCKER="/openbao/file",
            OPENBAO_NAME="openbao",
            container_port="8200",
            OPENBAO_SEAL_KEY_ID="0123456789abcdef",
            OPENBAO_SEAL_ROTATING=False,
            OPENBAO_AUDIT_PATH=values["OPENBAO_AUDIT_PATH"],
            OPENBAO_BASE_URL="https://bao.example.com",
        )
    )
    return list(AUDIT_STANZA.finditer(rendered))


def grants(policy: str) -> dict[str, set[str]]:
    """Return the capabilities a rendered policy grants per path pattern.

    Args:
        policy: the policy template's name without ``.hcl.j2``.
    """
    values = role_vars()
    rendered = (
        jinja_env()
        .get_template(f"policies/{policy}.hcl.j2")
        .render(
            **{
                key: value
                for key, value in values.items()
                if isinstance(value, str) and "{{" not in value
            }
        )
    )
    parsed = {
        match["path"]: set(re.findall(r'"([^"]+)"', match["caps"]))
        for match in POLICY_PATH.finditer(rendered)
    }
    if len(parsed) != rendered.count('path "'):
        raise AssertionError(f"{policy}: a path stanza escaped the parser")
    return parsed


def covers(pattern: str, path: str) -> bool:
    """Tell whether an OpenBao policy path pattern matches a request path.

    Args:
        pattern: the policy path, with ``+`` for one segment and a trailing ``*``.
        path: the request path.
    """
    regex = re.escape(pattern).replace(r"\+", "[^/]+")
    if regex.endswith(r"\*"):
        regex = regex[:-2] + ".*"
    return re.fullmatch(regex, path) is not None


def check_task(register: str) -> dict[str, Any]:
    tasks = load_yaml_any(str(ROLE_DIR / "tasks/03_policies.yml"))
    return next(task for task in tasks if task.get("register") == register)


def fails(register: str, result: dict[str, Any]) -> bool:
    """Evaluate a check's ``failed_when`` against one result.

    Args:
        register: the registered name of the check.
        result: what the check would have registered.
    """
    expression = jinja_env().compile_expression(check_task(register)["failed_when"])
    return bool(
        expression(
            **{register: result}, OPENBAO_AUDIT_PATH=role_vars()["OPENBAO_AUDIT_PATH"]
        )
    )


def audit_line(value: str, **request: str) -> str:
    """Return one audit response entry for the probe read, as OpenBao writes it.

    Args:
        value: the secret value as the entry carries it.
        request: overrides for the entry's ``request`` object.
    """
    values = role_vars()
    entry = {
        "time": "2026-11-03T10:00:00.123456Z",
        "type": "response",
        "auth": {"display_name": "approle", "policies": ["ansible-admin", "default"]},
        "request": {
            "operation": "read",
            "path": f"{values['OPENBAO_KV_MOUNT']}/data/{values['OPENBAO_AUDIT_PROBE']}",
            **request,
        },
        "response": {"data": {"data": {"value": value}}},
    }
    return json.dumps(entry, separators=(",", ":"))


def hashed(value: str) -> str:
    return "hmac-sha256:" + hashlib.sha256(value.encode()).hexdigest()


def run_log_check(register: str, log_lines: list[str]) -> dict[str, Any]:
    """Run a log check's shell command against a container log of given lines.

    Args:
        register: the registered name of the check.
        log_lines: the lines ``container logs`` prints.

    Returns:
        What the check registers: ``stdout`` and ``rc``.
    """
    values = role_vars()
    command = (
        jinja_env()
        .from_string(check_task(register)["ansible.builtin.shell"])
        .render(
            OPENBAO_LOCAL_CID="openbao-cid",
            OPENBAO_KV_MOUNT=values["OPENBAO_KV_MOUNT"],
            OPENBAO_AUDIT_PROBE=values["OPENBAO_AUDIT_PROBE"],
            openbao_audit_probe={"stdout": PROBE_VALUE + "\n"},
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


class TestTheAuditDeviceIsDeclared(unittest.TestCase):
    def test_the_server_declares_one_file_device_at_stdout(self) -> None:
        self.assertEqual(
            [(match["type"], match["path"]) for match in audit_stanzas()],
            [("file", "stdout")],
        )

    def test_the_device_writes_to_stdout(self) -> None:
        self.assertRegex(audit_stanzas()[0]["body"], r'file_path\s*=\s*"stdout"')

    def test_the_device_keeps_secret_values_hashed(self) -> None:
        self.assertNotRegex(audit_stanzas()[0]["body"], r'log_raw\s*=\s*"?true')


class TestOnlyTheAnsiblePolicyReachesSysAudit(unittest.TestCase):
    def test_ansible_admin_may_list_audit_devices(self) -> None:
        self.assertLessEqual({"read", "sudo"}, grants("ansible-admin")["sys/audit"])

    def test_no_human_policy_reaches_sys_audit(self) -> None:
        for policy in HUMAN_POLICIES:
            with self.subTest(policy=policy):
                self.assertEqual(
                    [
                        pattern
                        for pattern in grants(policy)
                        if covers(pattern, "sys/audit")
                        or covers(pattern, "sys/audit/stdout")
                    ],
                    [],
                )


class TestTheDeviceCheck(unittest.TestCase):
    def test_an_active_stdout_file_device_passes(self) -> None:
        devices = {"stdout/": {"type": "file", "path": "stdout/"}}
        self.assertFalse(
            fails("openbao_audit_devices", {"rc": 0, "stdout": json.dumps(devices)})
        )

    def test_a_missing_device_fails_the_deploy(self) -> None:
        self.assertTrue(fails("openbao_audit_devices", {"rc": 0, "stdout": "{}"}))

    def test_a_device_of_another_type_fails_the_deploy(self) -> None:
        devices = {"stdout/": {"type": "socket"}}
        self.assertTrue(
            fails("openbao_audit_devices", {"rc": 0, "stdout": json.dumps(devices)})
        )

    def test_the_device_check_never_reports_changed(self) -> None:
        self.assertIs(check_task("openbao_audit_devices")["changed_when"], False)


class TestTheProbeReadIsAudited(unittest.TestCase):
    def test_an_audited_probe_read_passes(self) -> None:
        result = run_log_check(
            "openbao_audit_entries", [audit_line(hashed(PROBE_VALUE))]
        )
        self.assertFalse(fails("openbao_audit_entries", result))

    def test_a_log_without_the_probe_read_fails_the_deploy(self) -> None:
        result = run_log_check(
            "openbao_audit_entries",
            ['{"@level":"info","@message":"core: vault is unsealed"}'],
        )
        self.assertTrue(fails("openbao_audit_entries", result))

    def test_a_read_of_another_path_fails_the_deploy(self) -> None:
        line = audit_line(hashed(PROBE_VALUE), path="infinito/data/other")
        result = run_log_check("openbao_audit_entries", [line])
        self.assertTrue(fails("openbao_audit_entries", result))

    def test_the_entry_check_never_reports_changed(self) -> None:
        self.assertIs(check_task("openbao_audit_entries")["changed_when"], False)


class TestThePlaintextLeakCheck(unittest.TestCase):
    def test_a_log_holding_only_the_hmac_passes(self) -> None:
        result = run_log_check("openbao_audit_leak", [audit_line(hashed(PROBE_VALUE))])
        self.assertFalse(fails("openbao_audit_leak", result))

    def test_a_plaintext_probe_value_fails_the_deploy(self) -> None:
        result = run_log_check("openbao_audit_leak", [audit_line(PROBE_VALUE)])
        self.assertTrue(fails("openbao_audit_leak", result))

    def test_the_leak_check_never_reports_changed(self) -> None:
        self.assertIs(check_task("openbao_audit_leak")["changed_when"], False)

    def test_both_log_checks_follow_the_probe_read(self) -> None:
        tasks = load_yaml_any(str(ROLE_DIR / "tasks/03_policies.yml"))
        order = [task.get("register") for task in tasks]
        probe = order.index("openbao_audit_probe")
        self.assertLess(probe, order.index("openbao_audit_entries"))
        self.assertLess(probe, order.index("openbao_audit_leak"))


if __name__ == "__main__":
    unittest.main()
