from __future__ import annotations

import json
import stat
import unittest

from ._fake_provision import CREDENTIALS, STATE_KEYS, WORKSPACE, TempCase, load

session = load("provision.session")


class TestBackend(TempCase):
    def setUp(self):
        super().setUp()
        self.config = {"cafile": "", "state": "https://s3.example.org"}

    def test_values_are_escaped_for_hcl(self):
        self.assertEqual(session._hcl('a${b}%{c}"'), '"a$${b}%%{c}\\""')

    def test_the_backend_file_is_private_and_written_once(self):
        keys = {**STATE_KEYS, "secret_key": "s${x}"}
        path = session.write_backend(self.root, self.config, "b", "SO/1.tfstate", keys)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn('secret_key = "s$${x}"\n', text)
        self.assertIn('endpoints = {\n  s3 = "https://s3.example.org"\n}\n', text)
        self.assertNotIn("custom_ca_bundle", text)
        with self.assertRaises(FileExistsError):
            session.write_backend(self.root, self.config, "b", "k", keys)

    def test_a_ca_file_reaches_the_backend(self):
        config = {**self.config, "cafile": "/etc/ssl/ca.pem"}
        path = session.write_backend(self.root, config, "b", "k", STATE_KEYS)
        text = path.read_text()  # nocheck: cache-read tempdir
        self.assertIn('custom_ca_bundle = "/etc/ssl/ca.pem"\n', text)


class TestEncryption(unittest.TestCase):
    def test_state_and_plan_are_enforced_with_the_workspace_transit_key(self):
        document = json.loads(session.encryption(WORKSPACE))
        key = document["key_provider"]["openbao"]["workspace"]
        self.assertEqual(key["key_name"], f"{WORKSPACE}-provision")
        self.assertEqual(key["transit_engine_path"], "/transit")
        for target in ("state", "plan"):
            self.assertEqual(
                document[target],
                {"method": "${method.aes_gcm.workspace}", "enforced": True},
            )


class TestCredentials(TempCase):
    def test_every_credential_name_is_cleared(self):
        names = session.credential_names(CREDENTIALS)
        self.assertLessEqual(
            {
                "AWS_ACCESS_KEY_ID",
                "CLOUDFLARE_API_TOKEN",
                "DNS_UPDATE_KEYSECRET",
                "HCLOUD_TOKEN",
                "IONOS_TOKEN",
                "OS_APPLICATION_CREDENTIAL_SECRET",
                "OS_AUTH_TYPE",
                "PROXMOX_VE_API_TOKEN",
                "INCUS_ADDR",
                "INCUS_CONF",
            },
            names,
        )


if __name__ == "__main__":
    unittest.main()
