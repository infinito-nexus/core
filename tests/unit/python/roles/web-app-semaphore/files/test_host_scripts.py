from __future__ import annotations

import json
import os
import re
import shutil
import unittest
from pathlib import Path, PurePosixPath

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

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
PAUSE = {"suspend": "stop", "resume": "start"}
APP_CONTROL_LINE = re.compile(r'^APP_CONTROL="(?P<command>[^"]+)"$', re.MULTILINE)
APP_CONTROL_USER_LINE = re.compile(r'^APP_CONTROL_USER="([^"]+)"$', re.MULTILINE)
BACKUP_USER_LINE = re.compile(r'^BACKUP_USER="([^"]+)"$', re.MULTILINE)
RELEASE_HELPER = "roles/web-app-semaphore/files/python/release_host.py"
COUNTS = {
    "agent_keys": 2,
    "app_control_keys": 1,
    "app_control_sudoers": 1,
    "backup_keys": 1,
    "backup_sudoers": 1,
}
APPLIED = {"rc": 0, "stdout": json.dumps({"kept": 1, "removed": COUNTS}) + "\n"}
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

    def host(self, env, args, directory=SCRIPTS_DIR):
        return self.runner.run(
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
        return self.host(
            env_for("release", SHIM_RESULTS=json.dumps(results)),
            ("release",),
            directory=directory,
        )

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
        apply, *proofs = self.runner.calls()
        workdir = apply["workdir"]
        inventory = f"{self.runner.checkout}/devices.yml"
        key = " ".join(self.public_key.split()[:2])
        self.assertEqual(
            apply["argv"],
            [
                HOST,
                "-i",
                inventory,
                "-b",
                "-t",
                f"{workdir}/release",
                "-m",
                "ansible.builtin.script",
                "-a",
                (
                    f"executable=python3 {self.runner.src}/{RELEASE_HELPER} apply"
                    " --login {{ ansible_user | quote }} --app-control-user app-control"
                    f" --backup-user backup --agent-key {key}"
                ),
            ],
        )
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
            '"${workdir}/release/${HOST}" \\\n'
            '\t\t"${workdir}/proof-login/${HOST}" "${workdir}/proof-root/${HOST}"'
        )
        self.assertIn(final, text)
        script.write_text(
            text.replace(final, '"${workdir}/release/${HOST}"'), encoding="utf-8"
        )
        run = self.release(
            {"ansible.builtin.script": APPLIED, "ansible.builtin.raw": {"rc": 0}},
            directory=planted,
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_release_of_a_released_host_refuses_before_any_write(self):
        run = self.release({"ansible.builtin.script": REFUSED_LOGIN})
        self.assertEqual(run.returncode, 2, run.stderr)
        line = self.last_line(run)
        self.assertEqual(set(line), {"host", "released", "refused"})
        self.assertFalse(line["released"])
        self.assertIn(f"{HOST} refuses the task agent key already", line["refused"])
        self.assertEqual(len(self.runner.calls()), 1)

    def test_a_refusal_of_the_helper_ends_the_release_without_a_proof(self):
        reason = "admin would keep no customer key ssh-keygen accepts"
        refused = {
            "rc": 2,
            "failed": True,
            "stdout": json.dumps({"refused": reason}) + "\n",
        }
        run = self.release({"ansible.builtin.script": refused})
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(
            self.last_line(run), {"host": HOST, "released": False, "refused": reason}
        )
        self.assertEqual(len(self.runner.calls()), 1)

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
