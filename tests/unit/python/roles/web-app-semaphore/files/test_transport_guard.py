from __future__ import annotations

import io
import json
import re
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from ansible.plugins.connection import ssh as ssh_plugin

from . import PROJECT_ROOT

GUARD = PROJECT_ROOT / "roles/web-app-semaphore/files/python/transport_guard.py"
BASE = {"ansible_user": "root", "ansible_host": "203.0.113.10"}


def load():
    """Returns:
    The loaded ``transport_guard`` module.
    """
    spec = spec_from_file_location("transport_guard", str(GUARD))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TransportGuardTests(unittest.TestCase):
    def setUp(self):
        self.mod = load()

    def test_settings_that_keep_the_pinned_options_first_pass(self):
        for extra in (
            {},
            {"ansible_connection": "ssh"},
            {"ansible_port": 2222},
            {"ansible_ssh_host_key_checking": False},
        ):
            with self.subTest(extra=extra):
                self.assertEqual(self.mod.findings({**BASE, **extra}), [])

    def test_settings_that_replace_the_pinned_transport_are_named(self):
        cases = {
            "ansible_ssh_args": "",
            "ansible_ssh_common_args": "-o ProxyCommand='sh -c id'",
            "ansible_ssh_extra_args": "-o PermitLocalCommand=yes -o LocalCommand=id",
            "ansible_scp_extra_args": "-o KnownHostsCommand=/bin/id",
            "ansible_sftp_extra_args": "-F /tmp/semaphore/repository/ssh_config",
            "ansible_ssh_executable": "/opt/ssh",
            "ansible_scp_executable": "/bin/sh",
            "ansible_sftp_executable": "/bin/sh",
            "ansible_ssh_pkcs11_provider": "/tmp/semaphore/repository/provider.so",
        }
        for name, value in cases.items():
            with self.subTest(name):
                self.assertEqual(
                    self.mod.findings({**BASE, name: value}), [f"{name} is set"]
                )
        with self.subTest("ansible_connection"):
            self.assertEqual(
                self.mod.findings({**BASE, "ansible_connection": "local"}),
                ["ansible_connection is not ssh"],
            )

    def test_the_refused_names_are_every_command_and_argument_option_of_the_ssh_plugin(
        self,
    ):
        names = set(re.findall(r"- name: (ansible_\w+)", ssh_plugin.DOCUMENTATION))
        expected = {
            name
            for name in names
            if name.endswith(("_args", "_executable", "_pkcs11_provider"))
        }
        self.assertEqual(set(self.mod.REFUSED), expected)

    def test_main_refuses_no_mapping_and_no_json(self):
        for stdin in ("[]", "{"):
            with self.subTest(stdin=stdin):
                stderr = io.StringIO()
                self.assertEqual(self.mod.main(io.StringIO(stdin), stderr), 1)
                self.assertIn("transport_guard.py:", stderr.getvalue())
        self.assertEqual(self.mod.main(io.StringIO(json.dumps(BASE)), io.StringIO()), 0)


if __name__ == "__main__":
    unittest.main()
