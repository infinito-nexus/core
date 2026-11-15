from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from ._fake_provision import CREDENTIALS, WORKSPACE, load

provider_env = load("provision.provider_env")
RefusedError = provider_env.inputs.RefusedError


class FakeBao:
    def read(self, path, fields):
        return {field: f"{path}#{field}" for field in fields}


class TestProviderEnvironment(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_provider_files_are_private_and_formatted(self):
        context = {"workspace": WORKSPACE, "zone": "z", "host": "target"}
        spec = CREDENTIALS["providers"]["incus"]
        environment = provider_env.provider_environment(
            FakeBao(), spec, context, self.root, "platform"
        )
        credentials = self.root / "credentials"
        self.assertEqual(environment["INCUS_REMOTE"], "target")
        self.assertEqual(environment["INCUS_CONF"], str(credentials))
        self.assertEqual(
            environment["INCUS_ADDR"], "platform/data/provision/incus-target#endpoint"
        )
        server = credentials / "servercerts" / "target.crt"
        self.assertEqual(
            server.read_text(),  # nocheck: cache-read tempdir
            "platform/data/provision/incus-target#certificate",
        )
        for path in (server, credentials / "client.crt", credentials / "client.key"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600, path)

    def test_a_host_that_would_leave_its_path_is_refused(self):
        spec = CREDENTIALS["providers"]["proxmox"]
        # nocheck: project-root-import  hostile host inputs of the fixture, not paths
        for host in ("", "../tenant", "a/b", "A", "..", "a..b", ".a", "a.", "-a"):
            context = {"workspace": WORKSPACE, "zone": "z", "host": host}
            with (
                self.subTest(host=host),
                self.assertRaisesRegex(RefusedError, "valid host"),
            ):
                provider_env.provider_environment(
                    FakeBao(), spec, context, self.root, "platform"
                )

    def test_a_dotted_inventory_hostname_names_its_provision_record(self):
        spec = CREDENTIALS["providers"]["proxmox"]
        context = {"workspace": WORKSPACE, "zone": "z", "host": "pve.example.org"}
        environment = provider_env.provider_environment(
            FakeBao(), spec, context, self.root, "platform"
        )
        self.assertEqual(
            environment["PROXMOX_VE_ENDPOINT"],
            "platform/data/provision/proxmox-pve.example.org#endpoint",
        )

    def test_the_proxmox_token_joins_token_id_and_secret(self):
        spec = CREDENTIALS["providers"]["proxmox"]
        context = {"workspace": WORKSPACE, "zone": "z", "host": "pve.example.org"}
        environment = provider_env.provider_environment(
            FakeBao(), spec, context, self.root, "platform"
        )
        record = f"tenant/data/{WORKSPACE}-provision/proxmox"
        self.assertEqual(
            environment["PROXMOX_VE_API_TOKEN"],
            f"{record}#token_id={record}#secret",
        )

    def test_a_template_reads_its_parts_and_a_plain_field_itself(self):
        self.assertEqual(
            provider_env.record_fields("{token_id}={secret}"), ["token_id", "secret"]
        )
        self.assertEqual(provider_env.record_fields("endpoint"), ["endpoint"])


if __name__ == "__main__":
    unittest.main()
