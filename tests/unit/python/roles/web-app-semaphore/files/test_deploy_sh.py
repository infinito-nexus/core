from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT
from ._script_shims import (
    HOST,
    HOST_KEY,
    REFERENCE,
    ScriptRunner,
    agent_gone,
    deploy_env,
    host_vars,
    planted_without_guard,
    planted_without_kill,
    planted_without_transport_guard,
    workspace_login,
)
from ._semaphore_fake import SCRIPTS_DIR, WORKSPACE_ID

SCRIPT = PROJECT_ROOT / "roles/web-app-semaphore/files/shell/repository/deploy.sh"
PASSWORD = "vault-password-4711"
OTHER_WORKSPACE = "11111111-2222-4333-8444-555555555555"


FAKE_INFINITO = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$FAKE_INFINITO_ARGS"
previous=""
for arg in "$@"; do
  if [ "$previous" = --password-file ]; then
    cat "$arg" > "$FAKE_INFINITO_PASSWORD"
  fi
  previous="$arg"
done
"""
VAULTED = """applications:
  web-app-foo:
    secrets:
      credentials:
        key: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          6162
"""
REFERENCED = """applications:
  web-app-foo:
    secrets:
      credentials:
        key:
          openbao: tenant/ws-a/key#value
"""


class DeployScriptTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.addCleanup(self.runner.cleanup)
        self.login, self.private_key, self.public_key = workspace_login(self)

    def deploy(self, env, reference=None, directory=SCRIPTS_DIR):
        login = dict(self.login)
        if reference is not None:
            login["SHIM_HOST_VARS"] = host_vars(reference, self.public_key)
        return self.runner.run(
            "deploy.sh", {**login, **env}, ("devices.yml",), directory=directory
        )

    def test_the_workspace_key_reaches_an_agent_in_the_workdir(self):
        run = self.deploy(deploy_env())
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.assertEqual(call["agent_socket"], f"{call['workdir']}/agent.sock")
        self.assertEqual(
            [line.split()[:2] for line in call["agent_keys"]],
            [self.public_key.split()[:2]],
        )
        self.assertEqual(call["known_hosts"], f"{HOST} {HOST_KEY}\n")

    def test_no_key_reaches_the_output(self):
        run = self.deploy(deploy_env())
        self.assertEqual(run.returncode, 0, run.stderr)
        body = self.private_key.splitlines()[1]
        self.assertNotIn(body, run.stdout + run.stderr)
        self.assertNotIn(body, "\n".join(self.runner.calls()[0]["argv"]))

    def test_a_key_outside_the_workspace_is_refused(self):
        cases = {
            "another workspace": {
                "openbao": f"tenant/ws-{OTHER_WORKSPACE}/ssh#private_key"
            },
            "another mount": {"openbao": f"platform/ws-{WORKSPACE_ID}/ssh#private_key"},
            "a plain value": self.private_key,
        }
        for name, reference in cases.items():
            with self.subTest(name):
                run = self.deploy(deploy_env(), reference=reference)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("workspace_ssh_key.py: ", run.stderr)
                self.assertEqual(self.runner.calls(), [])
                self.assertNotIn(
                    self.private_key.splitlines()[1], run.stdout + run.stderr
                )

    def test_an_inventory_locking_the_deploy_out_is_refused_before_the_host(self):
        cases = {
            "key missing": (
                host_vars(REFERENCE, None),
                "users.root.authorized_keys lacks ssh-ed25519 SHA256:",
            ),
            "root login no": (
                host_vars(REFERENCE, self.public_key, "no"),
                "SYS_SVC_SSHD_PERMIT_ROOT_LOGIN is no while the login user is root",
            ),
        }
        for case, (variables, refusal) in cases.items():
            with self.subTest(case):
                run = self.deploy(deploy_env(SHIM_HOST_VARS=variables))
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(f"lockout_guard.py: {refusal}", run.stderr)
                self.assertEqual(self.runner.calls(), [])
        with self.subTest("negative control: without the guard the deploy runs"):
            planted = planted_without_guard(self.runner.tmp)
            run = self.deploy(
                deploy_env(SHIM_HOST_VARS=host_vars(REFERENCE, None)),
                directory=planted,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(self.runner.calls()), 1)

    def test_an_inventory_replacing_the_pinned_transport_is_refused(self):
        variables = json.dumps(
            {
                **json.loads(host_vars(REFERENCE, self.public_key)),
                "ansible_ssh_args": "-o StrictHostKeyChecking=no",
            }
        )
        run = self.deploy(deploy_env(SHIM_HOST_VARS=variables))
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertIn("transport_guard.py: the inventory overrides", run.stderr)
        self.assertIn("ansible_ssh_args is set", run.stderr)
        self.assertEqual(self.runner.calls(), [])
        with self.subTest("negative control: without the guard the deploy runs"):
            planted = planted_without_transport_guard(self.runner.tmp)
            run = self.deploy(deploy_env(SHIM_HOST_VARS=variables), directory=planted)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(self.runner.calls()), 1)

    def test_the_agent_and_its_socket_are_gone_after_the_task(self):
        run = self.deploy(deploy_env())
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.assertFalse(Path(call["agent_socket"]).exists())
        self.assertTrue(agent_gone(call["agent_pid"]))

    def test_negative_control_an_agent_left_running_is_found(self):
        planted = planted_without_kill(self.runner.tmp)
        run = self.deploy(deploy_env(), directory=planted)
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.addCleanup(os.kill, int(call["agent_pid"]), 15)
        self.assertFalse(agent_gone(call["agent_pid"]))

    def test_deploy_sh_refuses_each_malformed_deploy_input(self):
        cases = [
            ("SALES_ORDER", {"SALES_ORDER": None}, "SALES_ORDER is missing"),
            ("SALES_ORDER", {"SALES_ORDER": "1; rm"}, "SALES_ORDER is malformed"),
            ("LINE", {"LINE": None}, "LINE is missing"),
            ("LINE", {"LINE": "one"}, "LINE is malformed"),
            ("LINE", {"LINE": "0"}, "LINE is malformed"),
            ("LINE", {"LINE": "007"}, "LINE is malformed"),
            ("HOST_KEY", {"HOST_KEY": None}, "HOST_KEY is missing"),
            ("HOST_KEY", {"HOST_KEY": "ssh-dss AAAA"}, "HOST_KEY is malformed"),
            ("DNS_LABEL", {"DNS_LABEL": None}, "DNS_LABEL is missing"),
            ("DNS_LABEL", {"DNS_LABEL": "Wiki."}, "DNS_LABEL is malformed"),
            (
                "HOST",
                {"HOST": "198.51.100.9"},
                "HOST 198.51.100.9 is not the host of a pair",
            ),
            ("ROLES", {"ROLES": "web-app-absent"}, "ROLES names web-app-absent"),
            (
                "WORKSPACE_DNS_ZONE",
                {"WORKSPACE_DNS_ZONE": None},
                "WORKSPACE_DNS_ZONE is missing",
            ),
            (
                "INVENTORY_COMMIT",
                {"INVENTORY_COMMIT": "main"},
                "INVENTORY_COMMIT is malformed",
            ),
        ]
        for name, overrides, message in cases:
            with self.subTest(f"{name}: {overrides}"):
                run = self.deploy(deploy_env(**overrides))
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(f"deploy.sh: {message}", run.stderr)
                self.assertEqual(self.runner.calls(), [])

    def test_an_empty_target_list_refuses_every_host(self):
        run = self.deploy(deploy_env(WORKSPACE_TARGETS=""))
        self.assertEqual(run.returncode, 2)
        self.assertIn(
            f"HOST {HOST} is not the host of a pair in WORKSPACE_TARGETS", run.stderr
        )

    def test_deploy_sh_builds_the_domain_and_pins_the_host_key(self):
        run = self.deploy(deploy_env())
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.assertEqual(call["name"], "infinito")
        self.assertIn(
            f"DOMAIN_PRIMARY=wiki.ws-{WORKSPACE_ID}.ws.example.org", call["argv"]
        )
        self.assertEqual(call["argv"][call["argv"].index("--limit") + 1], HOST)
        self.assertEqual(call["argv"][call["argv"].index("--id") + 1], "web-app-wiki")
        self.assertEqual(call["known_hosts"], f"{HOST} {HOST_KEY}\n")
        self.assertIn("StrictHostKeyChecking=yes", call["ssh"])
        self.assertIn("GlobalKnownHostsFile=/dev/null", call["ssh"])

    def test_deploy_sh_moves_the_control_path_into_its_workdir(self):
        run = self.deploy(deploy_env())
        self.assertEqual(run.returncode, 0, run.stderr)
        (call,) = self.runner.calls()
        self.assertTrue(call["workdir_exists"])
        self.assertFalse(Path(call["workdir"]).exists())
        self.assertNotIn("~/.ssh", call["ssh"])


class TestDeployShVaultPassword(unittest.TestCase):
    def run_deploy(
        self, host_vars: str, password: str | None
    ) -> tuple[subprocess.CompletedProcess[str], list[str], str]:
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            repository = root / "repository"
            (repository / "host_vars").mkdir(parents=True)
            (repository / "devices.yml").write_text("all: {}\n", encoding="utf-8")
            (repository / "host_vars" / "host.yml").write_text(
                host_vars, encoding="utf-8"
            )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "infinito"
            fake.write_text(FAKE_INFINITO, encoding="utf-8")
            fake.chmod(0o755)
            (root / "home").mkdir()
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "HOME": str(root / "home"),
                "DEPLOY_LOGIN": "deploy",
                "DEPLOY_KNOWN_HOSTS": "",
                "SSH_AUTH_SOCK": str(root / "agent.sock"),
                "FAKE_INFINITO_ARGS": str(root / "args"),
                "FAKE_INFINITO_PASSWORD": str(root / "password"),
            }
            if password is not None:
                env["DEPLOY_VAULT_PASSWORD"] = password
            completed = subprocess.run(
                ["bash", str(SCRIPT), "devices.yml"],
                cwd=repository,
                env=env,
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
            )
            args_file = root / "args"
            args = (
                args_file.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
                if args_file.exists()
                else ""
            ).splitlines()
            password_file = root / "password"
            seen = (
                password_file.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
                if password_file.exists()
                else ""
            )
        return completed, args, seen

    def test_deploy_sh_needs_a_vault_password_only_for_vault_blocks(self) -> None:
        completed, args, _ = self.run_deploy(REFERENCED, None)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("--password-file", args)
        self.assertEqual(args[:4], ["administration", "deploy", "dedicated", args[3]])

    def test_a_vault_block_still_needs_the_password(self) -> None:
        completed, args, _ = self.run_deploy(VAULTED, None)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("vault password", completed.stderr)
        self.assertEqual(args, [])

    def test_a_vault_block_hands_the_password_as_a_file(self) -> None:
        completed, args, seen = self.run_deploy(VAULTED, PASSWORD)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--password-file", args)
        self.assertEqual(seen, PASSWORD)
        self.assertNotIn(PASSWORD, "\n".join(args))


if __name__ == "__main__":
    unittest.main()
