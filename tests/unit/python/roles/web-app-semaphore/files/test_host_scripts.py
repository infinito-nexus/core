from __future__ import annotations

import json
import os
import re
import shutil
import signal as signal_module
import subprocess
import sys
import time
import unittest
from pathlib import Path, PurePosixPath

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.platform_monitoring import configuration_base, digest_path
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT
from ._script_shims import (
    HOST,
    HOST_KEY,
    REFERENCE,
    ScriptRunner,
    agent_gone,
    host_env,
    host_vars,
    planted_without_guard,
    planted_without_kill,
    planted_without_transport_guard,
    workspace_login,
)
from ._semaphore_fake import SCRIPTS_DIR, WORKSPACE_ID

ACTIONS = ("update", "backup", "restart", "suspend", "resume")
GUARDED = (*ACTIONS, "release")
NO_COMMIT = ("restart", "suspend", "resume", "release")
LABELLED = ("update",)
LABEL = "wiki"
PRIMARY = f"{LABEL}.ws-{WORKSPACE_ID}.ws.example.org"
PAUSE = {"suspend": "stop", "resume": "start"}
APP_CONTROL_LINE = re.compile(r'^APP_CONTROL="(?P<command>[^"]+)"$', re.MULTILINE)
APP_CONTROL_USER_LINE = re.compile(r'^APP_CONTROL_USER="([^"]+)"$', re.MULTILINE)
BACKUP_USER_LINE = re.compile(r'^BACKUP_USER="([^"]+)"$', re.MULTILINE)
RELEASE_HELPER = "roles/web-app-semaphore/files/python/release/host.py"
FEDERATION_DIGEST = digest_path(configuration_base(PROJECT_ROOT))
COUNTS = {
    "agent_keys": 2,
    "app_control_keys": 1,
    "app_control_sudoers": 1,
    "backup_keys": 1,
    "backup_sudoers": 1,
    "federation_token": 1,
    "monitoring_agent": 1,
    "monitoring_key": 1,
}
BASE_COUNTS = {
    "agent_keys": 2,
    "app_control_keys": 1,
    "app_control_sudoers": 1,
    "backup_keys": 1,
    "backup_sudoers": 1,
}
PRE_138_APPLIED = {
    "rc": 0,
    "stdout": json.dumps({"kept": 1, "removed": BASE_COUNTS}, sort_keys=True) + "\n",
}
PRE_138_LINE = (
    '{"host": "203.0.113.10", "kept": 1, "released": true, "removed": '
    '{"agent_keys": 2, "app_control_keys": 1, "app_control_sudoers": 1, '
    '"backup_keys": 1, "backup_sudoers": 1}}'
)
PROMETHEUS_ADDRESS = "198.51.100.8"
CHECKED = {"rc": 0, "stdout": json.dumps({"checked": True}) + "\n"}
LATE_PYTHON = """#!/bin/sh
case "$*" in
*"$BLOCK_ON"*) touch "$SHIM_LATE"; sleep 2 ;;
esac
exec {real} "$@"
"""
SHARE_COUNTS = {"federation_token": 1, "monitoring_agent": 1}
SHARED = {"rc": 0, "stdout": json.dumps({"removed": SHARE_COUNTS}) + "\n"}
APPLIED = {
    "rc": 0,
    "stdout": json.dumps(
        {"kept": 1, "removed": {**COUNTS, "federation_token": 0, "monitoring_agent": 0}}
    )
    + "\n",
}
MARKER = f"monitoring/ws-{WORKSPACE_ID}/released/{HOST}"
RECORDS = [
    f"platform/metadata/monitoring/federation/ws-{WORKSPACE_ID}/{HOST}",
    f"monitoring/metadata/ws-{WORKSPACE_ID}/federation/{HOST}",
    f"monitoring/metadata/ws-{WORKSPACE_ID}/agent/{HOST}",
]
CLAIM = f"monitoring/ws-{WORKSPACE_ID}/releasing/{HOST}"
DIGEST_RECORD = f"monitoring/ws-{WORKSPACE_ID}/federation/{HOST}"
MONITORED = f"platform/monitoring/inventory/ws-{WORKSPACE_ID}/hosts/{HOST}"
TOMBSTONE = {
    "proof": {"removed": {"federation_token": 1}},
    "digest_file": FEDERATION_DIGEST,
    "at": "earlier",
}
REFUSED_LOGIN = {
    "unreachable": True,
    "msg": f"Failed to connect to the host via ssh: root@{HOST}: "
    "Permission denied (publickey).",
}
PROOF_ARGS = (
    "-o ControlMaster=no",
    "-o ControlPath=none",
    "-o BatchMode=yes",
    "-o IdentitiesOnly=yes",
    "-o StrictHostKeyChecking=yes",
    "-o GlobalKnownHostsFile=/dev/null",
)
KEY_SCRIPTS = ("deploy.sh", "host.sh")
OWN_AGENT = re.compile(r"\bssh-(?:agent|add)\b|workspace_ssh_key\.py")
LOADER_CALL = re.compile(r'^\s*load_workspace_key "\$\{inventory\}"$', re.MULTILINE)


def loader_findings(directory):
    """Args:
    directory: the folder holding the repository scripts.

    Returns:
        One message per script of ``KEY_SCRIPTS`` that starts an agent,
        adds a key or calls the key helper itself, or never calls the shared
        ``load_workspace_key`` of ``lib.sh``, and one when ``lib.sh`` lacks it.
    """
    findings = []
    for name in KEY_SCRIPTS:
        text = (directory / name).read_text(
            encoding="utf-8"
        )  # nocheck: cache-read tempdir
        if OWN_AGENT.search(text):
            findings.append(f"{name} starts an SSH agent itself")
        if not LOADER_CALL.search(text):
            findings.append(f"{name} does not call load_workspace_key")
    lib = (directory / "lib.sh").read_text(
        encoding="utf-8"
    )  # nocheck: cache-read tempdir
    if "load_workspace_key() {" not in lib or not OWN_AGENT.search(lib):
        findings.append("lib.sh holds no load_workspace_key")
    return findings


def env_for(action, **overrides):
    """Args:
    action: one of ``ACTIONS``.
    overrides: variables to set; None drops one.

    Returns:
        A valid environment of the action with ``overrides`` applied.
    """
    if action in NO_COMMIT:
        overrides = {"INVENTORY_COMMIT": None, **overrides}
    if action in LABELLED:
        overrides = {"DNS_LABEL": LABEL, **overrides}
    if action == "release":
        overrides = {"PLATFORM_PROMETHEUS_ADDRESS": PROMETHEUS_ADDRESS, **overrides}
    return host_env(**overrides)


def deployed_app_control():
    """Returns:
    The ``app-control`` call with its configuration that a core deploy installs.
    """
    values = {}
    for name in ("00_general.yml", "05_paths.yml"):
        values.update(load_yaml_any(str(PROJECT_ROOT / "group_vars/all" / name)))
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["path_join"] = lambda parts: str(PurePosixPath(*parts))
    resolved = dict(values)
    for key in ("SOFTWARE_DOMAIN", "BIN_APP_CONTROL", "FILE_APP_CONTROL_CONFIG"):
        resolved[key] = env.from_string(values[key]).render(**resolved)
    return (
        f"{resolved['BIN_APP_CONTROL']} --config {resolved['FILE_APP_CONTROL_CONFIG']}"
    )


def app_control_findings(script):
    """Args:
    script: the text of ``host.sh``.

    Returns:
        Every way its ``APP_CONTROL`` call strays from the one a deploy installs.
    """
    found = APP_CONTROL_LINE.findall(script)
    if found != [deployed_app_control()]:
        return [f"APP_CONTROL {found} != {deployed_app_control()}"]
    return []


def inverse_findings(suspend, resume):
    """Args:
    suspend: the ``argv`` of the ansible call of ``suspend``.
    resume: the same of ``resume``.

    Returns:
        Every way the two calls are not the stop and start of the same target.
    """
    findings = []
    if suspend[:-1] != resume[:-1]:
        findings.append(f"the calls differ before the command: {suspend} {resume}")
    if suspend[-1].rsplit(" ", 2)[1:] != ["stop", "all"]:
        findings.append(f"suspend runs {suspend[-1]}")
    if resume[-1].rsplit(" ", 2)[1:] != ["start", "all"]:
        findings.append(f"resume runs {resume[-1]}")
    if suspend[-1].rsplit(" ", 2)[0] != resume[-1].rsplit(" ", 2)[0]:
        findings.append("suspend and resume call another app-control")
    return findings


class HostScriptTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.addCleanup(self.runner.cleanup)
        self.login, self.private_key, self.public_key = workspace_login(self)
        self.bao.put(MONITORED, {"digest_files": [FEDERATION_DIGEST]})

    def host(self, env, args, directory=SCRIPTS_DIR):
        return self.runner.run(
            "host.sh", {**self.login, **env}, args, directory=directory
        )

    def started(self, env, args, directory=SCRIPTS_DIR):
        return self.runner.start(
            "host.sh", {**self.login, **env}, args, directory=directory
        )

    def run_action(self, action):
        run = self.host(env_for(action), (action,))
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        return call

    def test_each_host_script_loads_the_workspace_key_into_its_task_agent(self):
        for action in ACTIONS:
            with self.subTest(action):
                run = self.host(env_for(action), (action,))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(
                    "host.sh: the SSH key of WORKSPACE_SSH_KEY is in the task agent",
                    run.stdout,
                )
                (call,) = self.runner.calls()
                self.assertEqual(call["agent_socket"], f"{call['workdir']}/agent.sock")
                self.assertEqual(
                    [line.split()[:2] for line in call["agent_keys"]],
                    [self.public_key.split()[:2]],
                )
                self.assertNotIn(
                    self.private_key.splitlines()[1], run.stdout + run.stderr
                )
                self.assertFalse(Path(call["agent_socket"]).exists())
                self.assertTrue(agent_gone(call["agent_pid"]))

    def test_a_key_outside_the_workspace_stops_every_host_script(self):
        for action in GUARDED:
            with self.subTest(action):
                run = self.host(
                    env_for(
                        action,
                        SHIM_HOST_VARS=host_vars(
                            {"openbao": f"platform/ws-{WORKSPACE_ID}/ssh#private_key"},
                            self.public_key,
                        ),
                    ),
                    (action,),
                )
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("workspace_ssh_key.py: ", run.stderr)
                self.assertEqual(self.runner.calls(), [])

    def lockouts(self):
        """Returns:
        ``{case: (host variables, refusal)}`` of inventories under which the
        task would lose its key login.
        """
        return {
            "key missing": (
                host_vars(REFERENCE, None),
                "users.root.authorized_keys lacks ssh-ed25519 SHA256:",
            ),
            "root login no": (
                host_vars(REFERENCE, self.public_key, "no"),
                "SYS_SVC_SSHD_PERMIT_ROOT_LOGIN is no while the login user is root",
            ),
            "role default": (
                host_vars(REFERENCE, self.public_key, None),
                "SYS_SVC_SSHD_PERMIT_ROOT_LOGIN is no while the login user is root",
            ),
        }

    def test_an_inventory_locking_the_task_out_stops_every_host_script(self):
        for action in GUARDED:
            for case, (variables, refusal) in self.lockouts().items():
                with self.subTest(action=action, case=case):
                    run = self.host(
                        env_for(action, SHIM_HOST_VARS=variables), (action,)
                    )
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(f"lockout_guard.py: {refusal}", run.stderr)
                    self.assertEqual(self.runner.calls(), [])
                    self.assertNotIn(
                        self.public_key.split()[1], run.stdout + run.stderr
                    )

    def transport_overrides(self):
        allowed = json.loads(host_vars(REFERENCE, self.public_key))
        return {
            name: json.dumps({**allowed, name: value})
            for name, value in (
                ("ansible_ssh_args", "-o StrictHostKeyChecking=no"),
                ("ansible_ssh_executable", "/usr/local/bin/ssh"),
                ("ansible_connection", "local"),
            )
        }

    def test_an_inventory_replacing_the_pinned_transport_stops_every_host_script(
        self,
    ):
        for action in GUARDED:
            for name, variables in self.transport_overrides().items():
                with self.subTest(action=action, variable=name):
                    run = self.host(
                        env_for(action, SHIM_HOST_VARS=variables), (action,)
                    )
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(
                        "transport_guard.py: the inventory overrides", run.stderr
                    )
                    self.assertIn(name, run.stderr)
                    self.assertEqual(self.runner.calls(), [])

    def test_negative_control_without_the_transport_guard_the_override_runs(self):
        planted = planted_without_transport_guard(self.runner.tmp)
        variables = self.transport_overrides()["ansible_ssh_args"]
        run = self.host(
            env_for("restart", SHIM_HOST_VARS=variables),
            ("restart",),
            directory=planted,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(self.runner.calls()), 1)

    def test_negative_control_without_the_guard_a_lockout_reaches_the_host(self):
        planted = planted_without_guard(self.runner.tmp)
        for case, (variables, _refusal) in self.lockouts().items():
            with self.subTest(case):
                run = self.host(
                    env_for("restart", SHIM_HOST_VARS=variables),
                    ("restart",),
                    directory=planted,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(len(self.runner.calls()), 1)

    def test_negative_control_a_host_agent_left_running_is_found(self):
        planted = planted_without_kill(self.runner.tmp)
        run = self.host(env_for("restart"), ("restart",), directory=planted)
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.addCleanup(os.kill, int(call["agent_pid"]), 15)
        self.assertFalse(agent_gone(call["agent_pid"]))

    def test_deploy_and_host_scripts_share_one_key_loader(self):  # nocheck: test.text-presence -- lint over every script of the directory  # fmt: skip
        self.assertEqual(loader_findings(SCRIPTS_DIR), [])

    def test_negative_control_a_script_starting_its_own_agent_is_caught(self):
        planted = Path(self.runner.tmp) / "own-agent"
        shutil.copytree(SCRIPTS_DIR, planted)
        script = planted / "host.sh"
        text = script.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        script.write_text(
            text.replace(
                'load_workspace_key "${inventory}"',
                'eval "$(ssh-agent -s)"',
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            loader_findings(planted),
            [
                "host.sh starts an SSH agent itself",
                "host.sh does not call load_workspace_key",
            ],
        )

    def test_each_host_script_pins_the_host_key(self):
        for action in ACTIONS:
            with self.subTest(action):
                call = self.run_action(action)
                self.assertEqual(call["known_hosts"], f"{HOST} {HOST_KEY}\n")
                self.assertIn("StrictHostKeyChecking=yes", call["ssh"])
                self.assertIn(HOST, call["argv"])

    def test_each_host_script_refuses_a_bad_host_or_key(self):
        cases = [
            ({"HOST_KEY": None}, "HOST_KEY is missing"),
            ({"HOST_KEY": "not a key"}, "HOST_KEY is malformed"),
            ({"HOST": "198.51.100.9"}, "HOST 198.51.100.9 is not the host of a pair"),
            ({"WORKSPACE_TARGETS": ""}, f"HOST {HOST} is not the host of a pair"),
        ]
        for action in GUARDED:
            for overrides, message in cases:
                with self.subTest(f"{action}: {overrides}"):
                    run = self.host(env_for(action, **overrides), (action,))
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(f"host.sh: {message}", run.stderr)
                    self.assertEqual(self.runner.calls(), [])

    def test_update_and_backup_need_a_commit_the_others_take_none(self):
        for action in ("update", "backup"):
            with self.subTest(action):
                run = self.runner.run(
                    "host.sh", env_for(action, INVENTORY_COMMIT=None), (action,)
                )
                self.assertEqual(run.returncode, 2)
                self.assertIn("INVENTORY_COMMIT is missing", run.stderr)
        for action in NO_COMMIT:
            with self.subTest(action):
                run = self.runner.run("host.sh", host_env(), (action,))
                self.assertEqual(run.returncode, 2)
                self.assertIn(
                    "INVENTORY_COMMIT is not taken by this action", run.stderr
                )
                self.assertEqual(self.runner.calls(), [])
                self.assertEqual(self.runner.git_calls(), [])

    def test_suspend_and_resume_refuse_any_further_argument(self):
        for action in PAUSE:
            with self.subTest(action):
                run = self.runner.run(
                    "host.sh", env_for(action), (action, "web-app-wiki")
                )
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("host.sh: unexpected argument 'web-app-wiki'", run.stderr)
                self.assertEqual(self.runner.calls(), [])

    def test_suspend_and_resume_pause_and_resume_every_application_as_root(self):
        for action, verb in PAUSE.items():
            with self.subTest(action):
                call = self.run_action(action)
                self.assertEqual(call["name"], "ansible")
                self.assertEqual(
                    call["argv"],
                    [
                        HOST,
                        "-i",
                        f"{self.runner.checkout}/devices.yml",
                        "-b",
                        "-m",
                        "ansible.builtin.command",
                        "-a",
                        f"{deployed_app_control()} {verb} all",
                    ],
                )
                self.assertEqual(self.runner.git_calls(), [])

    def test_suspend_and_resume_are_exact_inverses_and_repeat_unchanged(self):
        first = {action: self.run_action(action)["argv"] for action in PAUSE}
        again = {action: self.run_action(action)["argv"] for action in PAUSE}
        self.assertEqual(first, again)
        self.assertEqual(inverse_findings(first["suspend"], first["resume"]), [])

    def test_negative_control_a_resume_of_one_application_is_no_inverse(self):
        suspend = self.run_action("suspend")["argv"]
        resume = [*suspend[:-1], suspend[-1].replace("stop all", "start web-app-wiki")]
        self.assertNotEqual(inverse_findings(suspend, resume), [])

    def test_the_app_control_call_is_the_one_a_deploy_installs(self):
        script = read_text(str(SCRIPTS_DIR / "host.sh"))
        self.assertEqual(app_control_findings(script), [])

    def test_negative_control_a_drifted_config_path_fails(self):
        script = read_text(str(SCRIPTS_DIR / "host.sh"))
        planted = script.replace("/etc/infinito.nexus/", "/etc/infinito/")
        self.assertNotEqual(planted, script)
        self.assertNotEqual(app_control_findings(planted), [])

    def release(self, results, directory=SCRIPTS_DIR):
        shims = {
            "ansible.builtin.script:check": CHECKED,
            "ansible.builtin.script:share": SHARED,
            **results,
        }
        return self.host(
            env_for("release", SHIM_RESULTS=json.dumps(shims)),
            ("release",),
            directory=directory,
        )

    def release_calls(self):
        return [
            call
            for call in self.runner.calls()
            if " check --login " not in call["argv"][-1]
        ]

    def test_a_refused_release_writes_no_claim(self):
        reason = "admin would keep no customer key ssh-keygen accepts"
        refused = {
            "rc": 2,
            "failed": True,
            "stdout": json.dumps({"refused": reason}) + "\n",
        }
        run = self.release({"ansible.builtin.script:check": refused})
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(
            self.result_lines(run),
            [{"host": HOST, "released": False, "refused": reason}],
        )
        (check,) = self.runner.calls()
        self.assertIn(" check --login ", check["argv"][-1])
        self.assertNotIn(CLAIM, self.bao.kv)
        self.assertNotIn(MARKER, self.bao.kv)

    def test_negative_control_a_release_that_goes_on_claims(self):
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(CLAIM, self.bao.kv)

    def helper_calls(self, action):
        return [
            call["argv"][-1]
            for call in self.runner.calls()
            if f" {action} --login " in call["argv"][-1]
        ]

    def assert_the_check_gets_the_arguments_of_the_apply(self, applied):
        run = self.release(
            {"ansible.builtin.script": applied, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        (check,) = self.helper_calls("check")
        (apply,) = self.helper_calls("apply")
        self.assertEqual(check.replace(" check --login ", " apply --login "), apply)
        return check

    def test_the_check_of_a_monitored_host_gets_the_arguments_of_the_apply(self):
        check = self.assert_the_check_gets_the_arguments_of_the_apply(APPLIED)
        self.assertTrue(
            check.endswith(f" --federation-digest {FEDERATION_DIGEST} --monitoring"),
            check,
        )

    def test_the_check_of_a_never_monitored_host_gets_the_arguments_of_the_apply(
        self,
    ):
        self.bao.kv.pop(MONITORED)
        check = self.assert_the_check_gets_the_arguments_of_the_apply(PRE_138_APPLIED)
        self.assertTrue(
            check.endswith(f" --federation-digest {FEDERATION_DIGEST}"), check
        )

    def test_a_never_monitored_host_holding_the_share_writes_no_claim(self):
        self.bao.kv.pop(MONITORED)
        reason = "the host still holds the share: the monitoring key line"
        refused = {
            "rc": 2,
            "failed": True,
            "stdout": json.dumps({"refused": reason}) + "\n",
        }
        run = self.release({"ansible.builtin.script:check": refused})
        self.assertEqual(run.returncode, 2, run.stderr)
        (check,) = self.runner.calls()
        self.assertNotIn("--monitoring", check["argv"][-1])
        self.assertNotIn(CLAIM, self.bao.kv)

    def test_a_record_written_between_the_check_and_the_claim_stops_the_release(
        self,
    ):
        self.bao.kv.pop(MONITORED)
        handle = self.bao.handle

        def racing(handler, method, body):
            if method == "POST" and "/releasing/" in handler.path:
                self.bao.put(MONITORED, {"digest_files": [FEDERATION_DIGEST]})
            handle(handler, method, body)

        self.bao.handle = racing
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("changed between the check and the claim", run.stderr)
        self.assertEqual(
            self.result_lines(run),
            [
                {
                    "host": HOST,
                    "released": False,
                    "failed": f"the platform record of {HOST} changed between the"
                    " check and the claim; run the release again",
                }
            ],
        )
        (check,) = self.runner.calls()
        self.assertIn(" check --login ", check["argv"][-1])
        self.assertIn(CLAIM, self.bao.kv)

    def test_a_step_failing_without_a_result_ends_with_the_failed_line(self):
        (
            Path(self.runner.src) / "roles/svc-prx-openresty" / ROLE_FILE_META_VOLUMES
        ).unlink()
        run = self.release({})
        self.assertEqual(run.returncode, 1, run.stderr)
        (line,) = self.result_lines(run)
        self.assertEqual(line["host"], HOST)
        self.assertIs(line["released"], False)
        self.assertIn("before the release result", line["failed"])
        self.assertEqual(self.runner.calls(), [])
        self.assertNotIn(CLAIM, self.bao.kv)

    def test_a_refusal_before_any_helper_ends_with_the_refused_line(self):
        variables, _ = self.lockouts()["key missing"]
        run = self.host(env_for("release", SHIM_HOST_VARS=variables), ("release",))
        self.assertEqual(run.returncode, 2, run.stderr)
        (line,) = self.result_lines(run)
        self.assertEqual(set(line), {"host", "released", "refused"})
        self.assertIs(line["released"], False)

    def signalled(self, process, marker, signal):
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(marker.exists())
        process.send_signal(getattr(signal_module, signal))
        stdout, stderr = process.communicate(timeout=60)
        return subprocess.CompletedProcess(
            process.args, process.returncode, stdout, stderr
        )

    def late_signal(self, block_on, results):
        wrap = Path(self.runner.tmp) / "wrap"
        wrap.mkdir()
        python = wrap / "python3"
        python.write_text(LATE_PYTHON.format(real=sys.executable), encoding="utf-8")
        python.chmod(0o755)
        late = Path(self.runner.tmp) / "late"
        shims = {
            "ansible.builtin.script:check": CHECKED,
            "ansible.builtin.script:share": SHARED,
            **results,
        }
        process = self.started(
            env_for(
                "release",
                SHIM_RESULTS=json.dumps(shims),
                BLOCK_ON=block_on,
                SHIM_LATE=str(late),
                PATH=os.pathsep.join(
                    (str(wrap), str(self.runner.bin), os.environ["PATH"])
                ),
            ),
            ("release",),
        )
        return self.signalled(process, late, "SIGTERM")

    def test_a_signal_during_the_final_report_keeps_the_release(self):
        run = self.late_signal(
            "proof-root/",
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN},
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        (line,) = self.result_lines(run)
        self.assertEqual(
            line, {"host": HOST, "kept": 1, "released": True, "removed": COUNTS}
        )

    def test_a_signal_during_a_refusing_check_keeps_the_refusal(self):
        reason = "admin would keep no customer key ssh-keygen accepts"
        refused = {
            "rc": 2,
            "failed": True,
            "stdout": json.dumps({"refused": reason}) + "\n",
        }
        run = self.late_signal(
            "proof_of_release.py check", {"ansible.builtin.script:check": refused}
        )
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(
            self.result_lines(run),
            [{"host": HOST, "released": False, "refused": reason}],
        )
        self.assertNotIn(CLAIM, self.bao.kv)

    def test_a_signal_during_a_step_ends_with_the_failed_line(self):
        for signal in ("SIGTERM", "SIGHUP", "SIGINT"):
            with self.subTest(signal=signal):
                block = Path(self.runner.tmp) / f"block-{signal}"
                shims = {"ansible.builtin.script:check": CHECKED}
                process = self.started(
                    env_for(
                        "release",
                        SHIM_RESULTS=json.dumps(shims),
                        SHIM_BLOCK=str(block),
                    ),
                    ("release",),
                )
                run = self.signalled(process, block, signal)
                self.assertEqual(run.returncode, 1, run.stderr)
                self.assertEqual(
                    self.result_lines(run),
                    [
                        {
                            "host": HOST,
                            "released": False,
                            "failed": f"host.sh got {signal}; run the release again",
                        }
                    ],
                )
                self.assertNotIn(CLAIM, self.bao.kv)

    def test_a_release_without_its_proof_helper_refuses_before_the_workdir(self):
        for value in ("", str(Path(self.runner.tmp) / "nowhere")):
            with self.subTest(value=value):
                run = self.host(
                    env_for("release", INFINITO_SRC_DIR=value), ("release",)
                )
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("names no core tree holding", run.stderr)
                self.assertEqual(self.runner.calls(), [])

    def test_a_helper_result_line_is_never_followed_by_a_second(self):
        self.bao.put(MONITORED, {"digest_files": []})
        run = self.release({})
        self.assertEqual(run.returncode, 1, run.stderr)
        (line,) = self.result_lines(run)
        self.assertIn("names no digest file", line["failed"])

    def result_lines(self, run):
        lines = []
        for text in run.stdout.splitlines():
            try:
                line = json.loads(text)
            except ValueError:
                continue
            if isinstance(line, dict) and "released" in line:
                lines.append(line)
        self.assertEqual(lines[-1:], [json.loads(run.stdout.splitlines()[-1])])
        return lines

    def last_line(self, run):
        return json.loads(run.stdout.splitlines()[-1])

    def test_release_runs_the_helper_as_root_then_proves_a_fresh_login_fails(self):
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            self.last_line(run),
            {"host": HOST, "kept": 1, "released": True, "removed": COUNTS},
        )
        share, apply, *proofs = self.release_calls()
        workdir = apply["workdir"]
        inventory = f"{self.runner.checkout}/devices.yml"
        key = " ".join(self.public_key.split()[:2])
        for call, action, tree in (
            (share, "share", "share"),
            (apply, "apply", "release"),
        ):
            with self.subTest(action=action):
                self.assertEqual(
                    call["argv"],
                    [
                        HOST,
                        "-i",
                        inventory,
                        "-b",
                        "-t",
                        f"{workdir}/{tree}",
                        "-m",
                        "ansible.builtin.script",
                        "-a",
                        (
                            f"executable=python3 {self.runner.src}/{RELEASE_HELPER}"
                            f" {action} --login {{{{ ansible_user | quote }}}}"
                            " --app-control-user app-control"
                            f" --backup-user backup --agent-key {key}"
                            f" --federation-digest {FEDERATION_DIGEST} --monitoring"
                        ),
                    ],
                )
        self.assertIn(
            ("POST", f"monitoring/data/ws-{WORKSPACE_ID}/released/{HOST}"),
            [(method, path) for method, path, _ in self.bao.requests],
        )
        self.assertEqual(self.bao.kv[MARKER][-1]["proof"], {"removed": SHARE_COUNTS})
        self.assertNotIn("digest_file", self.bao.kv[MARKER][-1])
        self.assertIn(CLAIM, self.bao.kv)
        self.assertEqual(len(proofs), 2)
        for proof, name, user in zip(
            proofs, ("proof-login", "proof-root"), (None, "root"), strict=True
        ):
            with self.subTest(proof=name):
                self.assertEqual(
                    proof["argv"],
                    [
                        HOST,
                        "-i",
                        inventory,
                        "-e",
                        f"@{workdir}/{name}.json",
                        "-t",
                        f"{workdir}/{name}",
                        "-m",
                        "ansible.builtin.raw",
                        "-a",
                        "true",
                    ],
                )
                pinned = proof["operation"]
                self.assertEqual(pinned.get("ansible_user"), user)
                self.assertEqual(
                    pinned["ansible_ssh_private_key_file"], f"{workdir}/agent.pub"
                )
                for option in (
                    *PROOF_ARGS,
                    f"-o UserKnownHostsFile={workdir}/known_hosts",
                ):
                    self.assertIn(option, pinned["ansible_ssh_args"])
                self.assertNotIn("ControlPersist", pinned["ansible_ssh_args"])
                self.assertEqual(proof["known_hosts"], f"{HOST} {HOST_KEY}\n")
                self.assertEqual(
                    [k.split()[:2] for k in proof["agent_keys"]], [key.split()]
                )
        self.assertTrue(agent_gone(apply["agent_pid"]))

    def test_a_worker_releases_and_leaves_the_stack_digest_to_its_manager(self):
        for groups in (
            {"svc-swarm-manager": {"hosts": ["manager"]}},
            {
                "svc-swarm-manager": {"children": ["mgr"]},
                "mgr": {"hosts": ["10.0.0.2"]},
            },
        ):
            with self.subTest(groups=groups):
                variables = {**json.loads(self.login["SHIM_HOST_VARS"]), **groups}
                run = self.host(
                    env_for(
                        "release",
                        SHIM_RESULTS=json.dumps(
                            {
                                "ansible.builtin.script:check": CHECKED,
                                "ansible.builtin.script:share": SHARED,
                                "ansible.builtin.script": APPLIED,
                                "ansible.builtin.raw": REFUSED_LOGIN,
                            }
                        ),
                        SHIM_HOST_VARS=json.dumps(variables),
                    ),
                    ("release",),
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(f"{HOST} is a worker of", run.stderr)
                self.assertEqual(self.last_line(run)["released"], True)
                helpers = [
                    call["argv"][-1]
                    for call in self.release_calls()
                    if "ansible.builtin.script" in call["argv"]
                ]
                self.assertTrue(helpers)
                for helper in helpers:
                    self.assertNotIn("--federation-digest", helper)
                self.assertEqual(self.erases()[-3:], RECORDS)

    def erases(self):
        return [path for method, path, _ in self.bao.requests if method == "DELETE"]

    def test_a_failing_helper_erases_no_federation_record(self):
        for result in (
            {"rc": 1, "failed": True, "stdout": json.dumps({"failed": "x"}) + "\n"},
            {"rc": 2, "failed": True, "stdout": json.dumps({"refused": "x"}) + "\n"},
        ):
            for step in ("ansible.builtin.script:share", "ansible.builtin.script"):
                with self.subTest(result=result, step=step):
                    run = self.release({step: result})
                    self.assertNotEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(self.erases(), [])

    def test_a_marker_the_task_cannot_write_drops_no_key(self):
        self.bao.tokens = {
            token: [prefix for prefix in prefixes if "/released/" not in prefix]
            for token, prefixes in self.bao.tokens.items()
        }
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("released", self.last_line(run)["failed"])
        (share,) = self.release_calls()
        self.assertIn(" share --login ", share["argv"][-1])
        self.assertEqual(self.erases(), [])

    def test_negative_control_a_released_helper_erases_every_record(self):
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(self.erases(), RECORDS)
        self.assertIn(MARKER, self.bao.kv)

    def test_the_release_checks_every_digest_file_the_platform_record_names(self):
        recorded = "/srv/openresty/conf.d/federate.sha256"
        self.bao.put(MONITORED, {"digest_files": [FEDERATION_DIGEST, recorded]})
        self.assertNotIn(DIGEST_RECORD, self.bao.kv)
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        for call in self.release_calls()[:2]:
            self.assertTrue(
                call["argv"][-1].endswith(
                    f" --federation-digest {FEDERATION_DIGEST} {recorded} --monitoring"
                ),
                call["argv"][-1],
            )
        self.assertIn(MONITORED, self.bao.kv)

    def test_the_release_also_checks_the_digest_file_of_the_runner_core(self):
        recorded = "/srv/openresty/conf.d/federate.sha256"
        self.bao.put(MONITORED, {"digest_files": [recorded]})
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        for call in self.release_calls()[:2]:
            self.assertTrue(
                call["argv"][-1].endswith(
                    f" --federation-digest {recorded} {FEDERATION_DIGEST} --monitoring"
                ),
                call["argv"][-1],
            )

    def test_a_tombstone_never_names_the_digest_file(self):
        self.bao.kv.pop(MONITORED)
        self.bao.put(MARKER, TOMBSTONE)
        run = self.release(
            {
                "ansible.builtin.script": PRE_138_APPLIED,
                "ansible.builtin.raw": REFUSED_LOGIN,
            }
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(f"{HOST} was never monitored", run.stderr)
        helper = self.release_calls()[0]["argv"][-1]
        self.assertTrue(
            helper.endswith(f" --federation-digest {FEDERATION_DIGEST}"), helper
        )

    def pre_138_release(self, **env):
        shims = {
            "ansible.builtin.script:check": CHECKED,
            "ansible.builtin.script": PRE_138_APPLIED,
            "ansible.builtin.raw": REFUSED_LOGIN,
        }
        return self.host(
            env_for("release", SHIM_RESULTS=json.dumps(shims), **env), ("release",)
        )

    def assert_pre_138(self, run):
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.splitlines()[-1], PRE_138_LINE)
        self.assertNotIn("is a worker of", run.stderr)
        apply, *proofs = self.release_calls()
        self.assertEqual(len(proofs), 2)
        self.assertTrue(
            apply["argv"][-1].endswith(
                f" apply --login {{{{ ansible_user | quote }}}}"
                " --app-control-user app-control --backup-user backup"
                f" --agent-key {self.agent_key()}"
                f" --federation-digest {FEDERATION_DIGEST}"
            ),
            apply["argv"][-1],
        )
        self.assertNotIn(MARKER, self.bao.kv)
        self.assertEqual(self.erases(), [])

    def test_a_platform_without_monitoring_releases_as_before_138(self):
        self.bao.requests.clear()
        run = self.pre_138_release(PLATFORM_PROMETHEUS_ADDRESS=None)
        self.assert_pre_138(run)
        self.assertEqual(
            [path for _, path, _ in self.bao.requests if "monitoring" in path], []
        )
        self.assertNotIn(CLAIM, self.bao.kv)

    def test_a_never_monitored_host_releases_as_before_138(self):
        self.bao.kv.pop(MONITORED)
        run = self.pre_138_release()
        self.assert_pre_138(run)
        self.assertIn(f"{HOST} was never monitored", run.stderr)

    def test_negative_control_a_monitored_host_counts_the_share(self):
        run = self.pre_138_release()
        self.assertNotEqual(run.stdout.splitlines()[-1:], [PRE_138_LINE])

    def agent_key(self):
        return " ".join(self.public_key.split()[:2])

    def test_a_failed_token_erase_keeps_the_tombstone_and_the_rerun_retries(self):
        token = f"platform/monitoring/federation/ws-{WORKSPACE_ID}/{HOST}"
        self.bao.put(token, {"token": "t"})
        granted = self.bao.tokens
        self.bao.tokens = {
            name: [
                prefix
                for prefix in prefixes
                if not prefix.startswith("platform/monitoring/federation/")
            ]
            for name, prefixes in granted.items()
        }
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn(f"erasing {token} answered 403", self.last_line(run)["failed"])
        self.assertEqual(self.erases(), RECORDS[:1])
        self.assertIn(MARKER, self.bao.kv)
        self.assertIn(token, self.bao.kv)
        self.bao.tokens = granted
        run = self.rerun()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            self.last_line(run), {"already": True, "host": HOST, "released": True}
        )
        self.assertNotIn(token, self.bao.kv)
        self.assertIn(MARKER, self.bao.kv)

    def test_update_deploys_with_the_domain_of_deploy_domain(self):
        call = self.run_action("update")
        self.assertEqual(call["argv"][-2:], ["-e", f"DOMAIN_PRIMARY={PRIMARY}"])

    def test_update_without_a_label_keeps_the_inventory_domain(self):
        for label in (None, ""):
            with self.subTest(label=label):
                run = self.host(env_for("update", DNS_LABEL=label), ("update",))
                self.assertEqual(run.returncode, 0, run.stderr)
                call = self.runner.calls()[-1]
                self.assertNotIn("-e", call["argv"])
                self.assertEqual(call["argv"][-2:], ["--limit", HOST])

    def test_update_refuses_a_malformed_label(self):
        for action in LABELLED:
            for label, message in (
                ("Wiki", "DNS_LABEL is malformed"),
                ("wiki.evil.net", "DNS_LABEL is malformed"),
                ("-wiki", "DNS_LABEL is malformed"),
            ):
                with self.subTest(action=action, label=label):
                    run = self.host(env_for(action, DNS_LABEL=label), (action,))
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(f"host.sh: {message}", run.stderr)
                    self.assertEqual(self.runner.calls(), [])
                    self.assertEqual(self.runner.git_calls(), [])

    def test_the_other_actions_take_no_label(self):
        for action in ("backup", "restart", "suspend", "resume", "release"):
            with self.subTest(action=action):
                run = self.host(env_for(action, DNS_LABEL=LABEL), (action,))
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("DNS_LABEL is not taken by this action", run.stderr)

    def test_release_fails_when_the_agent_key_still_logs_in(self):
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": {"rc": 0}}
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(
            self.last_line(run),
            {
                "host": HOST,
                "released": False,
                "failed": f"the task agent key still logs in to {HOST} after the release",
            },
        )

    def test_negative_control_without_the_proof_a_live_key_passes(self):
        planted = Path(self.runner.tmp) / "no-proof"
        shutil.copytree(SCRIPTS_DIR, planted)
        script = planted / "host.sh"
        text = script.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        final = (
            '"${result}" \\\n'
            '\t\t"${workdir}/proof-login/${HOST}" "${workdir}/proof-root/${HOST}"'
        )
        self.assertIn(final, text)
        script.write_text(text.replace(final, '"${result}"'), encoding="utf-8")
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": {"rc": 0}},
            directory=planted,
        )
        self.assertNotIn("still logs in", run.stdout + run.stderr)

    def rerun(self, proof=REFUSED_LOGIN):
        return self.release(
            {
                "ansible.builtin.script:share": REFUSED_LOGIN,
                "ansible.builtin.script": APPLIED,
                "ansible.builtin.raw": proof,
            }
        )

    def test_a_rerun_after_a_failed_erase_erases_and_ends_released(self):
        self.bao.put(MARKER, TOMBSTONE)
        run = self.rerun()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            self.last_line(run), {"already": True, "host": HOST, "released": True}
        )
        self.assertEqual(len(self.release_calls()), 3)
        self.assertEqual(self.erases(), RECORDS)

    def test_a_strictmodes_refusal_without_a_release_marker_fails_loud(self):
        token = f"platform/monitoring/federation/ws-{WORKSPACE_ID}/{HOST}"
        for kept in ((token, MONITORED), (MONITORED,)):
            with self.subTest(kept=kept):
                if token in kept:
                    self.bao.put(token, {"token": "t"})
                    self.addCleanup(self.bao.kv.pop, token, None)
                else:
                    self.bao.kv.pop(token, None)
                run = self.rerun()
                self.assertEqual(run.returncode, 1, run.stderr)
                failed = self.last_line(run)["failed"]
                self.assertIn(
                    f"{HOST} refuses the platform key and no release marker proves",
                    failed,
                )
                self.assertIn(
                    "remove the agent binary, the monitoring key line and the "
                    "federation digest file manually",
                    failed,
                )
                self.assertEqual(len(self.release_calls()), 1)
                self.assertEqual(self.erases(), [])

    def test_a_refusal_of_a_never_monitored_host_without_a_tombstone_fails_loud(
        self,
    ):
        self.bao.kv.pop(MONITORED)
        self.bao.put(MARKER, TOMBSTONE)
        run = self.release(
            {
                "ansible.builtin.script": REFUSED_LOGIN,
                "ansible.builtin.raw": REFUSED_LOGIN,
            }
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertEqual(
            self.last_line(run),
            {
                "host": HOST,
                "released": False,
                "failed": f"the release on {HOST} ended without its result",
            },
        )
        self.assertEqual(len(self.release_calls()), 1)
        self.assertEqual(self.erases(), [])

    def test_a_platform_record_naming_no_digest_file_fails_before_any_call(self):
        self.bao.put(MONITORED, {"digest_files": ["/etc/passwd"]})
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("no digest file", self.last_line(run)["failed"])
        self.assertEqual((self.release_calls(), self.erases()), ([], []))

    def test_a_retried_complete_release_finds_its_tombstone_and_ends_released(self):
        first = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": REFUSED_LOGIN}
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        run = self.rerun()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(
            self.last_line(run), {"already": True, "host": HOST, "released": True}
        )
        self.assertEqual(len(self.release_calls()), 3)
        self.assertIn(MARKER, self.bao.kv)

    def test_negative_control_a_rerun_the_key_still_logs_in_to_fails(self):
        self.bao.put(MARKER, TOMBSTONE)
        run = self.rerun(proof={"rc": 0})
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("still logs in", self.last_line(run)["failed"])

    def test_a_refusal_of_the_helper_ends_the_release_without_a_proof(self):
        reason = "admin would keep no customer key ssh-keygen accepts"
        refused = {
            "rc": 2,
            "failed": True,
            "stdout": json.dumps({"refused": reason}) + "\n",
        }
        run = self.release({"ansible.builtin.script:share": refused})
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(
            self.last_line(run), {"host": HOST, "released": False, "refused": reason}
        )
        self.assertEqual(len(self.release_calls()), 1)

    def test_the_release_names_the_accounts_a_deploy_creates(self):
        script = read_text(str(SCRIPTS_DIR / "host.sh"))
        paths = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/05_paths.yml"))
        tasks = load_yaml_any(str(PROJECT_ROOT / "roles/user-backup/tasks/00_core.yml"))
        self.assertEqual(
            APP_CONTROL_USER_LINE.findall(script), [paths["APP_CONTROL_USER"]]
        )
        self.assertEqual(
            BACKUP_USER_LINE.findall(script),
            [t["user"]["name"] for t in tasks if isinstance(t, dict) and "user" in t],
        )
        helper = read_text(str(PROJECT_ROOT / RELEASE_HELPER))
        (sudoers_dir,) = re.findall(r'^SUDOERS_DIR = "([^"]+)"$', helper, re.MULTILINE)
        (backup,) = BACKUP_USER_LINE.findall(script)
        self.assertIn(
            f"{sudoers_dir}/{backup}",
            [
                t["copy"]["dest"]
                for t in tasks
                if isinstance(t, dict) and isinstance(t.get("copy"), dict)
            ],
        )


if __name__ == "__main__":
    unittest.main()
