from __future__ import annotations

import json
import socket
import unittest

from utils.cache.files import read_text

from .provision._fake_provision import FILES, LOCK_ID, WORKSPACE, ZONE, Sandbox

RECORD_OBJECT = f"{WORKSPACE}-state/SO-2026/1.dns.tfstate"
CREATE = {"DNS_ACTION": "create", "HOST": "192.0.2.10", "DNS_LABEL": "shop"}
OWNER = f"shop.{WORKSPACE}.{ZONE}"
CNAME_CREATE = {
    **CREATE,
    "HOST": "box.example.org",
    "WORKSPACE_TARGETS": "192.0.2.10:22,box.example.org:2222",
}


class DnsCase(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox("knot")
        self.addCleanup(self.sandbox.close)

    def call(self, command):
        return next(c for c in self.sandbox.calls() if c["argv"][0] == command)


class TestInputs(DnsCase):
    def test_dns_sh_refuses_each_malformed_input(self):
        cases = {
            "DNS_ACTION": {"DNS_ACTION": "delete"},
            "SALES_ORDER": {"SALES_ORDER": "1SO"},
            "LINE": {"LINE": "1-2"},
            "DNS_LABEL": {"DNS_LABEL": "-shop"},
            "HOST": {"HOST": "Shop.Example", "WORKSPACE_TARGETS": "Shop.Example:22"},
            "WORKSPACE_TARGETS": {"HOST": "198.51.100.9"},
        }
        for name, values in cases.items():
            with self.subTest(name=name):
                result = self.sandbox.run("dns", **{**CREATE, **values})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(name, result.stderr)
                self.assertEqual(self.sandbox.calls(), [])

    def test_dns_sh_reads_no_file_of_the_checkout(self):
        (self.sandbox.checkout / "main.tf").write_text("planted", encoding="utf-8")
        (self.sandbox.checkout / "provision" / "SO-2026-1.tfvars.json").write_text(
            json.dumps({"dns_label": "other", "host": "203.0.113.1"}), encoding="utf-8"
        )
        result = self.sandbox.run("dns", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        apply = self.call("apply")
        self.assertEqual(
            json.loads(apply["texts"]["values.tfvars.json"]),
            {"dns_label": "shop", "host": "192.0.2.10", "cname": ""},
        )
        self.assertNotIn("main.tf", apply["texts"])

    def test_an_ipv6_host_of_the_targets_is_accepted(self):
        result = self.sandbox.run("dns", **{**CREATE, "HOST": "2001:DB8::10"})
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(self.call("apply")["texts"]["values.tfvars.json"])
        self.assertEqual(values["host"], "2001:db8::10")


class TestCname(DnsCase):
    def test_a_host_name_of_the_targets_writes_a_cname_and_is_never_resolved(self):
        result = self.sandbox.run("dns", **CNAME_CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(self.call("apply")["texts"]["values.tfvars.json"]),
            {"dns_label": "shop", "host": "", "cname": "box.example.org"},
        )
        self.assertEqual(
            {(name, kind) for name, kind, _ in self.sandbox.dns.questions},
            {(OWNER, 1), (OWNER, 28), (OWNER, 5)},
        )

    def test_negative_control_a_host_name_outside_the_targets_is_refused(self):
        result = self.sandbox.run(
            "dns", **{**CNAME_CREATE, "HOST": "other.example.org"}
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("WORKSPACE_TARGETS", result.stderr)
        self.assertEqual(self.sandbox.calls(), [])
        self.assertEqual(self.sandbox.dns.questions, [])

    def test_a_cname_refuses_a_name_that_holds_any_record(self):
        held = {
            1: socket.inet_aton("192.0.2.7"),
            28: socket.inet_pton(socket.AF_INET6, "2001:db8::7"),
            5: b"\x05other\x07example\x03org\x00",
        }
        for kind, data in held.items():
            with self.subTest(kind=kind):
                self.sandbox.dns.records.clear()
                self.sandbox.dns.records[(OWNER, kind)] = [data]
                result = self.sandbox.run("dns", **CNAME_CREATE)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("already holds an A, AAAA or CNAME record", result.stderr)
                self.assertEqual(self.sandbox.commands(), ["init"])


class TestRecordState(DnsCase):
    def test_the_record_state_has_its_own_key(self):
        result = self.sandbox.run("dns", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        init = self.call("init")
        self.assertIn(f'bucket = "{WORKSPACE}-state"\n', init["backend"]["text"])
        self.assertIn('key = "SO-2026/1.dns.tfstate"\n', init["backend"]["text"])
        self.assertEqual(init["backend"]["mode"], 0o600)
        versions = json.loads(init["texts"]["versions.tf.json"])
        self.assertIs(versions["terraform"]["backend"]["s3"]["use_lockfile"], True)
        self.assertEqual(
            init["texts"]["main.tf.json"],
            read_text(str(FILES / "opentofu" / "records" / "main.tf.json")),
        )
        self.assertIs(
            json.loads(init["env"]["TF_ENCRYPTION"])["state"]["enforced"], True
        )

    def test_create_refuses_a_name_that_holds_an_address(self):
        name = f"shop.{WORKSPACE}.{ZONE}"
        self.sandbox.dns.records[(name, 28)] = [
            socket.inet_pton(socket.AF_INET6, "2001:db8::7")
        ]
        result = self.sandbox.run("dns", **CREATE)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("already holds an A, AAAA or CNAME record", result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init"])

    def test_a_second_create_skips_the_check_of_its_own_record(self):
        self.sandbox.platform.objects[RECORD_OBJECT] = b"encrypted"
        self.sandbox.set_plan(
            {"state": ["module.dns.dns_a_record_set.record[0]"], "outputs": {}}
        )
        self.sandbox.dns.records[(f"shop.{WORKSPACE}.{ZONE}", 1)] = [
            socket.inet_aton("192.0.2.10")
        ]
        result = self.sandbox.run("dns", **CREATE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sandbox.commands(), ["init", "state", "apply", "output"])

    def test_remove_without_a_state_succeeds_with_nothing_to_do(self):
        result = self.sandbox.run("dns", DNS_ACTION="remove", HOST="", DNS_LABEL="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {"destroyed": [], "state": "deleted"},
        )
        self.assertEqual(self.sandbox.commands(), ["init"])

    def test_remove_of_an_empty_state_deletes_it_and_its_lock(self):
        objects = self.sandbox.platform.objects
        for key in (RECORD_OBJECT, f"{RECORD_OBJECT}.tflock"):
            objects[key] = b"encrypted"
        self.sandbox.set_plan({"state": [], "outputs": {}})
        result = self.sandbox.run("dns", DNS_ACTION="remove", HOST="", DNS_LABEL="")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout.splitlines()[-1]),
            {"destroyed": [], "state": "deleted"},
        )
        self.assertEqual(sorted(objects), [])
        self.assertNotIn("destroy", self.sandbox.commands())

    def test_remove_destroys_only_its_own_state(self):
        self.sandbox.platform.objects[RECORD_OBJECT] = b"encrypted"
        self.sandbox.set_plan(
            {"state": ["module.dns.dns_a_record_set.record[0]"], "outputs": {}}
        )
        result = self.sandbox.run("dns", DNS_ACTION="remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        destroy = self.call("destroy")
        self.assertIn(
            'key = "SO-2026/1.dns.tfstate"\n', self.call("init")["backend"]["text"]
        )
        self.assertEqual(
            json.loads(destroy["texts"]["values.tfvars.json"]),
            {"dns_label": "", "host": "", "cname": ""},
        )

    def test_remove_deletes_the_record_state_and_its_lock_only(self):
        objects = self.sandbox.platform.objects
        server = f"{WORKSPACE}-state/SO-2026/1.tfstate"
        for key in (RECORD_OBJECT, f"{RECORD_OBJECT}.tflock", server):
            objects[key] = b"encrypted"
        self.sandbox.set_plan(
            {"state": ["module.dns.dns_a_record_set.record[0]"], "outputs": {}}
        )
        result = self.sandbox.run("dns", DNS_ACTION="remove")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(objects), [server])

    def test_unlock_force_unlocks_the_record_state(self):
        self.sandbox.platform.objects[f"{RECORD_OBJECT}.tflock"] = json.dumps(
            {"ID": LOCK_ID}
        ).encode()
        result = self.sandbox.run("dns", DNS_ACTION="unlock")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.call("force-unlock")["argv"], ["force-unlock", "-force", LOCK_ID]
        )

    def test_a_lock_without_an_id_fails(self):
        self.sandbox.platform.objects[f"{RECORD_OBJECT}.tflock"] = json.dumps(
            {"ID": "-chdir=/"}
        ).encode()
        result = self.sandbox.run("dns", DNS_ACTION="unlock")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("force-unlock", self.sandbox.commands())


if __name__ == "__main__":
    unittest.main()
