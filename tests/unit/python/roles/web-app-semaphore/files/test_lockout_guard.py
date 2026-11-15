from __future__ import annotations

import io
import json
import subprocess
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from unittest import mock

from . import PROJECT_ROOT
from ._script_shims import key_pair

HELPER = PROJECT_ROOT / "roles/web-app-semaphore/files/python/lockout_guard.py"


def load_guard():
    """Returns:
    The module ``files/python/lockout_guard.py``.
    """
    spec = spec_from_file_location("lockout_guard", str(HELPER))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def keygen_fingerprint(public):
    """Args:
    public: an OpenSSH public key line.

    Returns:
        Its ``SHA256:`` fingerprint as ``ssh-keygen -l`` prints it.
    """
    listed = subprocess.run(
        ["ssh-keygen", "-l", "-f", "-"],
        input=public,
        capture_output=True,
        text=True,
        check=True,
    )
    return listed.stdout.split()[1]


def inventory(login, authorized, permit=None):
    """Args:
    login: ``ansible_user``.
    authorized: ``users.<login>.authorized_keys``.
    permit: ``SYS_SVC_SSHD_PERMIT_ROOT_LOGIN``, None to leave it unset.

    Returns:
        The host variables of a target.
    """
    variables = {
        "ansible_user": login,
        "users": {login: {"authorized_keys": authorized}},
    }
    if permit is not None:
        variables["SYS_SVC_SSHD_PERMIT_ROOT_LOGIN"] = permit
    return variables


class LockoutGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = load_guard()
        _private, self.public = key_pair()
        self.agent = [f"{self.public} task"]

    def refusal(self, host_vars, agent=None, default="no"):
        with self.assertRaises(self.guard.LockoutError) as caught:
            self.guard.check(host_vars, self.agent if agent is None else agent, default)
        message = str(caught.exception)
        self.assertNotIn(self.public.split()[1], message)
        return message

    def test_both_fine_passes(self):
        for permit in ("prohibit-password", "yes"):
            with self.subTest(permit):
                self.guard.check(
                    inventory("root", [self.public], permit), self.agent, "no"
                )

    def test_a_missing_key_is_refused_by_its_fingerprint(self):
        message = self.refusal(inventory("root", [], "prohibit-password"))
        self.assertIn("users.root.authorized_keys lacks", message)
        self.assertIn(keygen_fingerprint(self.public), message)

    def test_root_login_no_is_refused_by_the_setting(self):
        message = self.refusal(inventory("root", [self.public], "no"))
        self.assertEqual(
            message,
            "SYS_SVC_SSHD_PERMIT_ROOT_LOGIN is no while the login user is root; "
            "key login needs prohibit-password or yes",
        )

    def test_the_role_default_applies_when_the_inventory_sets_none(self):
        self.assertEqual(self.guard.sshd_default(), "no")
        self.refusal(
            inventory("root", [self.public]), default=self.guard.sshd_default()
        )
        self.guard.check(
            inventory("root", [self.public]), self.agent, "prohibit-password"
        )

    def test_an_unquoted_yaml_yes_is_no_keyword(self):
        message = self.refusal(inventory("root", [self.public], True))
        self.assertIn("is no PermitRootLogin keyword", message)

    def test_a_non_root_login_needs_its_own_key_and_no_root_login(self):
        self.guard.check(inventory("deploy", [self.public], "no"), self.agent, "no")
        variables = inventory("deploy", [])
        variables["users"]["root"] = {"authorized_keys": [self.public]}
        self.assertIn("users.deploy.authorized_keys lacks", self.refusal(variables))

    def test_options_and_comments_around_the_key_match(self):
        line = f'from="10.0.0.0/8",no-agent-forwarding {self.public} workspace'
        self.guard.check(
            inventory("root", [line], "prohibit-password"), self.agent, "no"
        )

    def test_negative_control_another_key_does_not_count(self):
        _other_private, other = key_pair()
        message = self.refusal(inventory("root", [other], "prohibit-password"))
        self.assertIn(keygen_fingerprint(self.public), message)
        self.assertNotIn(keygen_fingerprint(other), message)

    def test_fail_closed_inputs(self):
        cases = {
            "no login user": ({"users": {}}, self.agent, "names no valid ansible_user"),
            "empty agent": (
                inventory("root", [self.public], "yes"),
                [],
                "holds no key",
            ),
            "templated keys": (
                inventory("root", "{{ lookup('file', 'keys') }}", "yes"),
                self.agent,
                "is no list",
            ),
            "no mapping": ([], self.agent, "no mapping"),
        }
        for case, (host_vars, agent, expected) in cases.items():
            with self.subTest(case):
                self.assertIn(expected, self.refusal(host_vars, agent=agent))

    def test_main_reads_the_agent_and_reports_only_a_fingerprint(self):
        listed = subprocess.CompletedProcess([], 0, stdout=f"{self.public} task\n")
        stderr = io.StringIO()
        with mock.patch.object(self.guard.subprocess, "run", return_value=listed):
            status = self.guard.main(
                io.StringIO(json.dumps(inventory("root", [], "yes"))), stderr
            )
        self.assertEqual(status, 1)
        self.assertIn(
            "lockout_guard.py: users.root.authorized_keys lacks", stderr.getvalue()
        )
        self.assertNotIn(self.public.split()[1], stderr.getvalue())
        with mock.patch.object(self.guard.subprocess, "run", return_value=listed):
            status = self.guard.main(
                io.StringIO(json.dumps(inventory("root", [self.public], "yes"))),
                io.StringIO(),
            )
        self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
