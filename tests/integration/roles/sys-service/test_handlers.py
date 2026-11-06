from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_HANDLERS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "sys-service"
UNIT = "probe.service"
OMIT = "{{ omit }}"
STEP_SECONDS = 2
FAILED_RUN = "Result=exit-code\nExecMainStatus=69\n"
CLEAN_RUN = "Result=success\nExecMainStatus=0\n"
GATE_MESSAGE = f"Unable to start service {UNIT}. See shared service diagnostics above."

HOSTS = {
    "fresh-failure": ("restarted", CLEAN_RUN, FAILED_RUN),
    "fresh-success": ("restarted", FAILED_RUN, CLEAN_RUN),
    "no-state": (OMIT, FAILED_RUN, CLEAN_RUN),
}

FAKE_SYSTEMCTL = f"""#!{sys.executable}
import os
import sys
import time
from pathlib import Path

unit = Path(os.environ["FAKE_SYSTEMD_UNIT"])
words = [word for word in sys.argv[1:] if not word.startswith("--")]


def log(event):
    with (unit / "events").open("a") as events:
        events.write(event + "\\n")


def logged():
    return (unit / "events").read_text().split()


if words[0] == "daemon-reload":
    log("reload-begin")
    if (unit / "reload-waits-for-read").exists():
        deadline = time.monotonic() + 30
        while "read" not in logged() and time.monotonic() < deadline:
            time.sleep(0.1)
    else:
        time.sleep({STEP_SECONDS})
    log("reload-end")
elif words[0] == "show":
    if "-p" in words:
        log("read")
    print("LoadState=loaded")
    print("ActiveState=inactive")
    print((unit / "result").read_text(), end="")
elif words[0] == "is-enabled":
    print("static")
elif words[0] in ("start", "restart"):
    if "--no-block" in sys.argv:
        if os.fork():
            sys.exit(0)
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    log("start-begin")
    time.sleep({STEP_SECONDS})
    outcome = (unit / "next").read_text()
    (unit / "result").write_text(outcome)
    log("start-end")
    sys.exit(0 if outcome.startswith("Result=success") else 1)
"""

_RECAP = re.compile(
    r"^(?P<host>\S+)\s*:\s*ok=\d+\s+changed=\d+\s+"
    r"unreachable=\d+\s+failed=(?P<failed>\d+)",
    re.MULTILINE,
)


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _play() -> dict:
    return {
        "name": "A changed unit file notifies the sys-service handlers",
        "hosts": "all",
        "gather_facts": False,
        "environment": {"FAKE_SYSTEMD_UNIT": "{{ fake_unit_dir }}"},
        "vars_files": [
            str(PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"),
            str(ROLE / ROLE_FILE_VARS_MAIN),
        ],
        "vars": {"SYS_SERVICE_GROUP_MANIPULATION": []},
        "handlers": [
            {"ansible.builtin.import_tasks": str(ROLE / ROLE_FILE_HANDLERS_MAIN)}
        ],
        "tasks": [
            {
                "name": "Change the unit file",
                "ansible.builtin.command": "true",
                "changed_when": True,
                "notify": "refresh-systemctl-service",
            }
        ],
    }


def _run(work: Path) -> tuple[str, dict[str, int], dict[str, list[str]]]:
    """Notify the handlers once per host in one async ansible-playbook run.

    Args:
        work: an empty directory for the play, the fakes and their state.

    Returns:
        The play output, the failed count per host, and per host the events
        the fake ``systemctl`` recorded, in order.
    """
    bin_dir = work / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "systemctl", FAKE_SYSTEMCTL)
    dump_yaml(
        work / "role" / "tasks" / "utils" / "debug.yml",
        [
            {
                "name": "Fail the way the shared diagnostics do",
                "ansible.builtin.fail": {
                    "msg": "{{ system_service_debug_fail_message }}"
                },
            }
        ],
    )
    hosts = {}
    for host, (state, before, after) in HOSTS.items():
        unit = work / host
        unit.mkdir()
        (unit / "events").write_text("")
        (unit / "result").write_text(before)
        (unit / "next").write_text(after)
        if state == OMIT:
            (unit / "reload-waits-for-read").write_text("")
        hosts[host] = {
            "ansible_connection": "local",
            "ansible_python_interpreter": sys.executable,
            "fake_unit_dir": str(unit),
            "SYS_SERVICE_DEFAULT_STATE": state,
        }
    inventory = work / "inventory.yml"
    dump_yaml(inventory, {"all": {"hosts": hosts}})
    extra_vars = work / "extra-vars.yml"
    dump_yaml(
        extra_vars,
        {
            "ASYNC_ENABLED": True,
            "system_service_id": "probe",
            "system_service_name": UNIT,
            "system_service_scope": "user",
            "role_path": str(work / "role"),
        },
    )
    playbook = work / "play.yml"
    dump_yaml(playbook, [_play()])
    env = dict(os.environ)
    env.update(
        {
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_LOCAL_TEMP": str(work / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(work / "ansible-remote"),
            "ANSIBLE_ASYNC_DIR": str(work / "ansible-async"),
            "ANSIBLE_NOCOLOR": "1",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            str(inventory),
            "-e",
            f"@{extra_vars}",
            str(playbook),
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    failed = {m["host"]: int(m["failed"]) for m in _RECAP.finditer(result.stdout)}
    events = {host: read_text(str(work / host / "events")).split() for host in HOSTS}
    return result.stdout + result.stderr, failed, events


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestHandlersJudgeTheRunTheyStarted(unittest.TestCase):
    output: ClassVar[str] = ""
    failed: ClassVar[dict[str, int]] = {}
    events: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory(
            prefix="sys-service-handlers-", ignore_cleanup_errors=True
        ) as tmp:
            cls.output, cls.failed, cls.events = _run(Path(tmp))

    def test_a_requested_state_reloads_then_runs_then_reads_the_result(self):
        for host in ("fresh-failure", "fresh-success"):
            with self.subTest(host=host):
                self.assertEqual(
                    self.events[host],
                    ["reload-begin", "reload-end", "start-begin", "start-end", "read"],
                )

    def test_a_failed_run_fails_the_gate_after_a_clean_one(self):
        self.assertEqual(self.failed.get("fresh-failure"), 1, self.output)
        self.assertIn(GATE_MESSAGE, self.output)

    def test_a_clean_run_passes_the_gate_after_a_failed_one(self):
        self.assertEqual(self.failed.get("fresh-success"), 0, self.output)

    def test_without_a_requested_state_the_reload_stays_async_and_nothing_starts(
        self,
    ):
        self.assertEqual(self.failed.get("no-state"), 0, self.output)
        self.assertEqual(self.events["no-state"][:2], ["reload-begin", "read"])
        self.assertNotIn("start-begin", self.events["no-state"])


if __name__ == "__main__":
    unittest.main()
