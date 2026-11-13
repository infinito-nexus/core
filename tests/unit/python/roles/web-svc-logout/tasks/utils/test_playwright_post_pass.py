from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-svc-logout"
SCRIPT = ROLE / "files" / "shell" / "backchannel_failures.sh"
TASKS = ROLE / "tasks" / "utils" / "playwright_post_pass.yml"
SINCE = "1731442394.25"
SESSION = "6a1e9c2f-client-session"
RECEIVER = "https://logout.example.test/backchannel/web-app-xwiki"
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$@" >"${CALLS}"
printf '%s' "${LOG}"
printf '%s' "${ERR}" >&2
exit "${RC}"
"""


def answered(client: str, status: int) -> str:
    """Return the DEBUG line Keycloak logs for an answered back-channel call.

    Args:
        client: the client id of the call.
        status: the HTTP status the receiver answered with.
    """
    success = "true" if status in (200, 204) else "false"
    return (
        "2026-11-12 21:13:14,123 DEBUG [org.keycloak.services.managers."
        "ResourceAdminManager] (executor-thread-3) Received response for "
        f"backchannel-logout from client. clientId='{client}' "
        f"clientSessionId='{SESSION}' backchannelLogoutUrl='{RECEIVER}' "
        f"status={status} success={success}\n"
    )


def unreachable(client: str) -> str:
    """Return the warning Keycloak logs when a back-channel call gets no answer.

    Args:
        client: the client id of the call.
    """
    return (
        "2026-11-12 21:13:14,456 WARN  [org.keycloak.services] (executor-thread-3)"
        f" KC-SERVICES0057: Logout for client '{client}' failed: "
        "org.apache.http.conn.HttpHostConnectException: Connect to "
        "xwiki.example.test:443 failed: Connection refused\n"
    )


def run_check(
    log: str, swarm: bool, rc: int, err: str
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the failure collector against a stub container CLI.

    Args:
        log: what the stub prints as Keycloak's log.
        swarm: whether the collector reads a swarm service log.
        rc: the exit status of the stub.
        err: what the stub prints on stderr.

    Returns:
        The collector's result and the arguments the stub received.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stub_bin = Path(tmp) / "bin"
        stub_bin.mkdir()
        container = stub_bin / "container"
        container.write_text(STUB)
        container.chmod(0o755)
        calls = Path(tmp) / "calls"
        env = dict(os.environ)
        env.update(
            {
                "PATH": f"{stub_bin}:{env['PATH']}",
                "CALLS": str(calls),
                "LOG": log,
                "ERR": err,
                "RC": str(rc),
                "SINCE": SINCE,
                "SERVICE": "sso_keycloak" if swarm else "keycloak",
                "SWARM": "true" if swarm else "false",
            }
        )
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return result, read_text(str(calls)).splitlines()


def failure_message(result: subprocess.CompletedProcess) -> str | None:
    """Evaluate the fail task of the post-pass check against a collector result.

    Args:
        result: what the collector returned.

    Returns:
        The message the check fails with, or None when it passes.
    """
    check = load_yaml_any(str(TASKS))[0]["block"][1]
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    context = {
        "_logout_backchannel_failures": {
            "rc": result.returncode,
            "stdout_lines": result.stdout.splitlines(),
            "stderr_lines": result.stderr.splitlines(),
        }
    }
    if not env.compile_expression(check["when"])(**context):
        return None
    return env.from_string(check["ansible.builtin.fail"]["msg"]).render(**context)


class TestPlaywrightPostPass(unittest.TestCase):
    def test_a_compose_pass_reads_the_keycloak_container_since_the_start(self):
        result, calls = run_check("", swarm=False, rc=0, err="")
        self.assertEqual(calls, ["logs", "--since", SINCE, "keycloak"])
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_a_swarm_pass_reads_the_log_of_every_keycloak_task(self):
        log = "sso_keycloak.2@node-b    | " + answered("web-app-zammad", 503)
        result, calls = run_check(log, swarm=True, rc=0, err="")
        self.assertEqual(
            calls,
            ["service", "logs", "--no-task-ids", "--since", SINCE, "sso_keycloak"],
        )
        self.assertEqual(result.stdout.splitlines(), ["web-app-zammad 503"])

    def test_answered_calls_pass_the_check(self):
        log = (
            "2026-11-12 21:13:13,001 INFO  [org.keycloak.events] (executor-thread-1)"
            " type=LOGOUT\n" + answered("synapse", 200) + answered("web-app-xwiki", 204)
        )
        result, _ = run_check(log, swarm=False, rc=0, err="")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIsNone(failure_message(result))

    def test_a_stopped_receiver_fails_the_check(self):
        log = (
            answered("web-app-xwiki", 502)
            + unreachable("synapse")
            + answered("web-app-xwiki", 502)
            + answered("web-app-zammad", 204)
        )
        result, _ = run_check(log, swarm=False, rc=0, err="")
        self.assertEqual(
            result.stdout.splitlines(), ["synapse unreachable", "web-app-xwiki 502"]
        )
        self.assertEqual(
            failure_message(result),
            "Keycloak failed the back-channel logout call of "
            "synapse unreachable, web-app-xwiki 502",
        )

    def test_the_check_names_only_the_client_and_the_status(self):
        log = answered("web-app-xwiki", 500) + unreachable("synapse")
        result, _ = run_check(log, swarm=False, rc=0, err="")
        for secret in (SESSION, RECEIVER, "xwiki.example.test"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, result.stdout + result.stderr)

    def test_an_unreadable_log_fails_the_check(self):
        err = "Error response from daemon: No such container: keycloak\n"
        result, _ = run_check("", swarm=False, rc=1, err=err)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            failure_message(result),
            "reading the log of Keycloak failed: "
            "Error response from daemon: No such container: keycloak",
        )

    def test_the_task_passes_every_variable_the_collector_requires(self):
        required = set(re.findall(r': "\$\{(\w+):\?', read_text(str(SCRIPT))))
        collect = load_yaml_any(str(TASKS))[0]["block"][0]
        self.assertEqual(set(collect["environment"]), required)


if __name__ == "__main__":
    unittest.main()
