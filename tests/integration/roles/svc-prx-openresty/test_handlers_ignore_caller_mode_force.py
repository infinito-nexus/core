"""The OpenResty handlers must address OpenResty at the cluster's own mode.

A role that pins ``compose_mode_force`` in its vars (web-app-matrix's ansible
flavor, web-app-bigbluebutton) keeps that value in scope for every role it
includes, and for the svc-prx-openresty handler copy that
``tasks/utils/load/handlers.yml`` loads inside that chain. The
``container_address`` lookup honours the caller's override, so in a swarm
cluster the handlers asked for the compose name of a container that only exists
as a swarm task, tolerated the "no such container" and skipped the reload.

These cases run real Ansible over the real handler files and the real lookup:
the forced role's own probe reproduces the override, so the handler assertions
cannot pass vacuously.
"""

from __future__ import annotations

import os
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
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

LOAD_HANDLERS = str(PROJECT_ROOT / "tasks" / "utils" / "load" / "handlers.yml")
OPENRESTY_LOOKUP = "{{ lookup('container_address', 'svc-prx-openresty', 'openresty') }}"
SWARM_MARK = "swarm-task"
MODES = ("swarm", "compose")

FAKE_CONTAINER = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_CONTAINER_LOG"
"""

FAKE_RESOLVER = f"""#!/bin/sh
printf '{SWARM_MARK}:%s:%s' "$1" "$2"
"""


def _load_handlers_task() -> dict:
    return {
        "name": "Load the OpenResty handlers",
        "ansible.builtin.include_tasks": LOAD_HANDLERS,
        "vars": {"handler_role_name": "svc-prx-openresty"},
    }


ROLES: dict[str, dict[str, object]] = {
    "probe-forced": {
        ROLE_FILE_VARS_MAIN: {"compose_mode_force": "compose"},
        ROLE_FILE_TASKS_MAIN: [
            {
                "name": "Record what the forced scope resolves for OpenResty",
                "ansible.builtin.copy": {
                    "dest": "{{ forced_scope_out }}",
                    "content": OPENRESTY_LOOKUP,
                    "mode": "0644",
                },
            },
            {
                "name": "Serve a vhost the way sys-stk-front-proxy does",
                "ansible.builtin.include_role": {"name": "probe-front-proxy"},
            },
        ],
    },
    "probe-front-proxy": {
        ROLE_FILE_TASKS_MAIN: [
            {
                "name": "Bootstrap the front base",
                "ansible.builtin.include_role": {"name": "probe-front-base"},
            },
            {
                "name": "Change a vhost",
                "ansible.builtin.command": "true",
                "changed_when": True,
                "notify": "reload-openresty",
            },
            {
                "name": "Change the base configuration",
                "ansible.builtin.command": "true",
                "changed_when": True,
                "notify": "restart-openresty",
                "when": "notify_restart | bool",
            },
            {
                "name": "Run the notified handlers",
                "ansible.builtin.meta": "flush_handlers",
            },
        ],
    },
    "probe-front-base": {ROLE_FILE_TASKS_MAIN: [_load_handlers_task()]},
}


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _play(mode: str, resolver: Path, work: Path) -> dict:
    """Build the play for one cluster mode.

    Args:
        mode: the cluster ``DEPLOYMENT_MODE``, ``swarm`` or ``compose``.
        resolver: the fake swarm container-id resolver.
        work: the directory the play's output files land in.
    """
    swarm = mode == "swarm"
    return {
        "name": f"OpenResty handlers notified from a forced role ({mode})",
        "hosts": "localhost",
        "gather_facts": False,
        "connection": "local",
        "environment": {"FAKE_CONTAINER_LOG": str(work / f"{mode}-container.log")},
        "vars": {
            "ansible_python_interpreter": sys.executable,
            "DEPLOYMENT_MODE": mode,
            "IS_COMPOSE_MODE": not swarm,
            "IS_SWARM_MODE": swarm,
            "IS_STACK_HOST": False,
            "MODE_DEBUG": swarm,
            "STACK_HOST": "localhost",
            "BIN_RESOLVE_CONTAINER_ID": str(resolver),
            "notify_restart": swarm,
            "forced_scope_out": str(work / f"{mode}-forced-scope.txt"),
        },
        "tasks": [
            {
                "name": "Render the applications SPOT once, as the constructor does",
                "applications_carrier": {},
            },
            _load_handlers_task(),
            {
                "name": "Run the forced role the way tasks/utils/setup/role.yml does",
                "ansible.builtin.include_role": {"name": "probe-forced"},
                "vars": {"application_id": "web-app-forced"},
            },
        ],
    }


def _run(work: Path) -> dict[str, tuple[str, list[str]]]:
    """Run one play per cluster mode in a single ansible-playbook process.

    Args:
        work: an empty directory for the fixture roles, play and fakes.

    Returns:
        Per mode ``(forced_scope, calls)``: what the forced role itself resolved
        for OpenResty, and every argv the fake ``container`` CLI received.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    for role, files in ROLES.items():
        for relative, content in files.items():
            target = work / "roles" / role / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            dump_yaml(target, content)
    bin_dir = work / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "container", FAKE_CONTAINER)
    resolver = bin_dir / "resolve-container-id"
    _executable(resolver, FAKE_RESOLVER)
    playbook = work / "play.yml"
    dump_yaml(playbook, [_play(mode, resolver, work) for mode in MODES])
    env = dict(os.environ)
    env.update(
        {
            "ANSIBLE_CONFIG": str(PROJECT_ROOT / "ansible.cfg"),
            "ANSIBLE_LOCAL_TEMP": str(work / "ansible-local"),
            "ANSIBLE_REMOTE_TEMP": str(work / "ansible-remote"),
            "ANSIBLE_NOCOLOR": "1",
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
        }
    )
    result = subprocess.run(
        ["ansible-playbook", "-i", "localhost,", str(playbook)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    observed = {}
    for mode in MODES:
        log = read_text(str(work / f"{mode}-container.log"))
        observed[mode] = (
            read_text(str(work / f"{mode}-forced-scope.txt")),
            [line for line in log.splitlines() if line],
        )
    return observed


def _targets(calls: list[str], verb: str) -> list[str]:
    position = -1 if verb == "logs" else 1
    return [line.split()[position] for line in calls if line.startswith(f"{verb} ")]


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class TestOpenRestyHandlersIgnoreCallerModeForce(unittest.TestCase):
    observed: ClassVar[dict[str, tuple[str, list[str]]]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        """One ansible-playbook run answers every case, so it runs once."""
        with tempfile.TemporaryDirectory(prefix="openresty-mode-force-") as tmp:
            cls.observed = _run(Path(tmp))

    def test_the_forced_scope_really_forces_the_lookup(self) -> None:
        forced_scope, _ = self.observed["swarm"]
        self.assertEqual(
            forced_scope,
            "openresty",
            "the forced role must resolve OpenResty's compose name, or the "
            "handler cases below prove nothing",
        )

    def test_swarm_reload_validates_and_reloads_the_swarm_task(self) -> None:
        _, calls = self.observed["swarm"]
        execs = [line for line in calls if line.startswith("exec ")]
        self.assertIn("-s reload", " ".join(execs), calls)
        targets = _targets(calls, "exec")
        self.assertTrue(targets, calls)
        for target in targets:
            self.assertTrue(target.startswith(f"{SWARM_MARK}:"), calls)

    def test_swarm_restart_debug_logs_read_the_swarm_task(self) -> None:
        _, calls = self.observed["swarm"]
        targets = _targets(calls, "logs")
        self.assertTrue(targets, calls)
        for target in targets:
            self.assertTrue(target.startswith(f"{SWARM_MARK}:"), calls)

    def test_compose_cluster_keeps_the_compose_name(self) -> None:
        _, calls = self.observed["compose"]
        targets = _targets(calls, "exec")
        self.assertTrue(targets, calls)
        self.assertEqual(set(targets), {"openresty"}, calls)


if __name__ == "__main__":
    unittest.main()
