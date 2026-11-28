from __future__ import annotations

import io
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from . import PROJECT_ROOT

GUARD = PROJECT_ROOT / "roles/web-app-semaphore/files/python/inventory_guard.py"
HOST = "203.0.113.10"


def load():
    """Returns:
    The loaded ``inventory_guard`` module.
    """
    spec = spec_from_file_location("inventory_guard", str(GUARD))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def inventory(host_vars, group_vars=None):
    """Args:
    host_vars: the variables of the one host.
    group_vars: the ``vars`` of the group ``workspace``, None for no group.

    Returns:
        The inventory as ``ansible-inventory --list`` prints it.
    """
    listed = {
        "_meta": {"hostvars": {HOST: {"ansible_user": "admin", **host_vars}}},
        "all": {"children": ["ungrouped"]},
    }
    if group_vars is not None:
        listed["workspace"] = {"hosts": [HOST], "vars": group_vars}
    return listed


class InventoryGuardMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.mod = load()

    def guarded(self, listed):
        stderr = io.StringIO()
        code = self.mod.main(io.StringIO(json.dumps(listed)), stderr, PROJECT_ROOT)
        return code, stderr.getvalue()

    def test_platform_monitoring_is_no_core_setting(self):
        self.assertNotIn("platform_monitoring", self.mod.core_settings(PROJECT_ROOT))

    def test_a_valid_or_absent_share_passes(self):
        for host_vars in (
            {},
            {"platform_monitoring": {}},
            {"platform_monitoring": {"agent": False, "traffic": False}},
            {
                "platform_monitoring": {
                    "reachability": True,
                    "agent": True,
                    "health": True,
                    "system": False,
                    "traffic": True,
                }
            },
        ):
            with self.subTest(host_vars=host_vars):
                self.assertEqual(self.guarded(inventory(host_vars)), (0, ""))

    def test_a_broken_host_share_is_refused_with_its_place(self):
        for value, finding in (
            (
                {"logs": True},
                f"_meta.hostvars.{HOST}.platform_monitoring.logs is no share kind",
            ),
            (
                {"agent": "false"},
                f"_meta.hostvars.{HOST}.platform_monitoring.agent is no boolean",
            ),
            (False, f"_meta.hostvars.{HOST}.platform_monitoring is no mapping"),
        ):
            with self.subTest(value=value):
                code, stderr = self.guarded(inventory({"platform_monitoring": value}))
                self.assertEqual(code, 1)
                self.assertIn(finding, stderr)

    def test_a_broken_group_share_is_refused(self):
        code, stderr = self.guarded(
            inventory({}, {"platform_monitoring": {"health": 1}})
        )
        self.assertEqual(code, 1)
        self.assertIn("workspace.vars.platform_monitoring.health is no boolean", stderr)

    def test_ssh_host_key_is_no_core_setting(self):
        self.assertNotIn("ssh_host_key", self.mod.core_settings(PROJECT_ROOT))

    def test_a_host_key_line_of_every_allowed_type_passes(self):
        for key in host_keys().values():
            with self.subTest(key=key.split()[0]):
                self.assertEqual(
                    self.guarded(inventory({"ssh_host_key": key})), (0, "")
                )

    def test_anything_but_one_bare_host_key_line_is_refused(self):
        keys = host_keys()
        ed25519_key = keys["ssh-ed25519"]
        blob = ed25519_key.split()[1]
        for value in (
            f"{ed25519_key} root@host",
            f'from="*" {ed25519_key}',
            f"{ed25519_key}\n{keys['ssh-rsa']}",
            f"{ed25519_key}\n",
            f"ssh-dss {blob}",
            f"ssh-rsa {blob}",
            f"ssh-ed25519 {blob[:-4]}!!!!",
            f"ssh-ed25519  {blob}",
            "ssh-ed25519",
            "",
            [ed25519_key],
            None,
        ):
            with self.subTest(value=value):
                code, stderr = self.guarded(inventory({"ssh_host_key": value}))
                self.assertEqual(code, 1)
                self.assertIn(
                    f"_meta.hostvars.{HOST}.ssh_host_key is no OpenSSH host key line",
                    stderr,
                )

    def test_a_group_host_key_is_checked_too(self):
        code, stderr = self.guarded(inventory({}, {"ssh_host_key": "ssh-ed25519 AAAA"}))
        self.assertEqual(code, 1)
        self.assertIn("workspace.vars.ssh_host_key is no OpenSSH host key line", stderr)

    def test_only_the_host_key_and_the_share_stay_store_written(self):
        host_vars = {
            "ssh_host_key": host_keys()["ssh-ed25519"],
            "platform_monitoring": {"agent": True},
        }
        self.assertEqual(self.guarded(inventory(host_vars)), (0, ""))

    def test_negative_control_a_store_written_checkmk_value_is_refused(self):
        for name, block in (
            (ROLE, store_block()),
            (ROLE, {}),
            (
                ROLE,
                {
                    "secrets": {
                        "credentials": {
                            "federation_token_sha256": {
                                "openbao": "monitoring/ws-x/federation/h#federation_token_sha256"
                            }
                        }
                    }
                },
            ),
            ("web-app-checkmk", {"services": {"checkmk": {"site": "evil"}}}),
            ("web-app-checkmk", {}),
        ):
            for place, listed in (
                (f"_meta.hostvars.{HOST}", inventory({"applications": {name: block}})),
                ("workspace.vars", inventory({}, {"applications": {name: block}})),
            ):
                with self.subTest(name=name, block=block, place=place):
                    code, stderr = self.guarded(listed)
                    self.assertEqual(code, 1)
                    self.assertIn(
                        f"{place}.applications.{name} is the platform's to set", stderr
                    )

    def test_negative_control_another_role_block_is_not_this_checks_business(self):
        listed = inventory({"applications": {"web-app-wiki": {"compose": {}}}})
        self.assertEqual(self.guarded(listed), (0, ""))


ROLE = "svc-net-platform-monitoring"


def store_block():
    """Returns:
    ``applications.svc-net-platform-monitoring`` as ``agent_values`` of the
    store's ``services/platform_roles/monitoring/agent.py`` wrote it before
    the platform injected its Checkmk values.
    """
    checkmk = {"server": "checkmk.example.org", "address": "192.0.2.7"}
    return {"services": {"platform-monitoring": {"checkmk": checkmk}}}


def host_keys():
    """Returns:
    One fresh OpenSSH public key line per allowed type, by type.
    """
    generated = (
        ed25519.Ed25519PrivateKey.generate(),
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        ec.generate_private_key(ec.SECP256R1()),
        ec.generate_private_key(ec.SECP384R1()),
        ec.generate_private_key(ec.SECP521R1()),
    )
    lines = [
        key.public_key()
        .public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        .decode()
        for key in generated
    ]
    return {line.split()[0]: line for line in lines}


if __name__ == "__main__":
    unittest.main()
