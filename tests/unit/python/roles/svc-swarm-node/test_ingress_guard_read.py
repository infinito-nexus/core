"""The ingress guard read fails when the stack host cannot see the swarm's services.

The join and the refresh build the ingress guard and the onion backend drop
from this read. A stack host that is an active swarm member without control
would print nothing, and the onion backend drop would shrink to the configured
list while a stale host-mode publish still binds its port.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import jinja2

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

READ = (
    PROJECT_ROOT
    / "roles"
    / "svc-swarm-node"
    / "tasks"
    / "utils"
    / "ingress_guard"
    / "read.yml"
)
JOIN = PROJECT_ROOT / "roles" / "svc-swarm-node" / "tasks" / "00_core" / "join.yml"
FAKE_CONTAINER = """#!/bin/bash
case "$1 $2" in
  "info --format")
    format="$3"
    format="${format//'{{.Swarm.LocalNodeState}}'/$SWARM_STATE}"
    printf '%s\\n' "${format//'{{.Swarm.ControlAvailable}}'/$SWARM_CONTROL}"
    ;;
  "service ls") echo svc1 ;;
  "service inspect") echo "port null" ;;
  "node ls") echo node1 ;;
  "node inspect") echo "node 10.0.0.2" ;;
esac
"""


def read_script() -> str:
    """
    Returns:
        The read task's script, rendered as Ansible renders it.
    """
    (task,) = load_yaml_any(str(READ))
    return (
        jinja2.Environment(
            autoescape=jinja2.select_autoescape(default_for_string=False)
        )
        .from_string(task["ansible.builtin.shell"])
        .render()
    )


def run_read(state: str, control: str) -> subprocess.CompletedProcess[str]:
    """
    Args:
        state: the ``Swarm.LocalNodeState`` the stack host reports.
        control: the ``Swarm.ControlAvailable`` it reports.

    Returns:
        The read task's script run against a ``container`` CLI that reports
        *state* and *control*.
    """
    script = read_script()
    with tempfile.TemporaryDirectory() as bin_dir:
        fake = Path(bin_dir) / "container"
        fake.write_text(FAKE_CONTAINER)
        fake.chmod(0o755)
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": bin_dir + os.pathsep + os.environ["PATH"],
                "SWARM_STATE": state,
                "SWARM_CONTROL": control,
            },
        )


class TestIngressGuardRead(unittest.TestCase):
    def test_an_active_member_without_control_fails_the_read(self) -> None:
        result = run_read("active", "false")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_a_manager_prints_every_service_and_node(self) -> None:
        result = run_read("active", "true")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["port null", "node 10.0.0.2"])

    def test_a_host_outside_any_swarm_prints_nothing(self) -> None:
        result = run_read("inactive", "false")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_a_host_without_the_container_cli_fails_the_read(self) -> None:
        with tempfile.TemporaryDirectory() as empty_bin:
            result = subprocess.run(
                [shutil.which("bash"), "-c", read_script()],
                capture_output=True,
                text=True,
                check=False,
                env={"PATH": empty_bin},
            )
        self.assertEqual(result.returncode, 127, result.stderr)
        self.assertEqual(result.stdout, "")


class TestIngressGuardJoinOrder(unittest.TestCase):
    def test_the_container_cli_is_loaded_before_the_guard_reads_the_swarm(
        self,
    ) -> None:
        tasks = load_yaml_any(str(JOIN))
        load = next(
            (
                index
                for index, task in enumerate(tasks)
                if task.get("ansible.builtin.include_role", {}).get("name")
                == "sys-svc-container"
            ),
            None,
        )
        self.assertIsNotNone(load, "join.yml never loads sys-svc-container")
        guard = next(
            index
            for index, task in enumerate(tasks)
            if task.get("ansible.builtin.include_tasks") == "00_core/ingress_guard.yml"
        )
        self.assertLess(load, guard)


if __name__ == "__main__":
    unittest.main()
