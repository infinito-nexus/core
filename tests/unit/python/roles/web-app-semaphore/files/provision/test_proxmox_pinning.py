from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from ._fake_provision import CREDENTIALS, WORKSPACE, load

provider_env = load("provision.provider_env")
admission = load("provision.admission")
CERT_DIR = "SSL_CERT_DIR"
CONTEXT = {"workspace": WORKSPACE, "zone": "z", "host": "target"}


class FakeBao:
    def read(self, path, fields):
        return {field: f"{path}#{field}" for field in fields}


def tofu(specs, environ=None):
    """Args:
        specs: a decoded ``credentials.json``.
        environ: the spawner's environment, empty when None.

    Returns:
        The ``tofu`` :class:`admission.Program` the spawner builds.
    """
    pinned = admission.pinned_values(environ or {}, "/etc/tofurc", None, None)
    return admission.programs("/usr/bin/tofu", specs, pinned)["tofu"]


class TestProxmoxPinning(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.task = Path(directory.name)

    def environment(self, specs):
        return provider_env.provider_environment(
            FakeBao(), specs["providers"]["proxmox"], CONTEXT, self.task, "platform", {}
        )

    def test_the_provider_trusts_the_recorded_certificate_through_ssl_cert_dir(self):
        environment = self.environment(CREDENTIALS)
        servercerts = self.task / "credentials" / "servercerts"
        self.assertEqual(environment[CERT_DIR], str(servercerts))
        self.assertEqual(
            (servercerts / "target.crt").read_text(),  # nocheck: cache-read tempdir
            "platform/data/provision/proxmox-target#certificate",
        )
        self.assertEqual(
            environment["PROXMOX_VE_ENDPOINT"],
            "platform/data/provision/proxmox-target#endpoint",
        )

    def test_negative_control_a_mapping_without_the_certificate_is_caught(self):
        stripped = copy.deepcopy(CREDENTIALS)
        proxmox = stripped["providers"]["proxmox"]
        proxmox["env"] = {}
        del proxmox["secrets"][0]["files"]
        self.assertNotIn(CERT_DIR, self.environment(stripped))
        self.assertFalse((self.task / "credentials" / "servercerts").exists())

    def test_the_sandbox_admits_the_task_certificate_directory_only(self):
        entry = tofu(CREDENTIALS, {CERT_DIR: "/etc/ssl/certs"})
        self.assertNotIn(CERT_DIR, entry.pinned)
        self.assertIn(CERT_DIR, entry.files)
        inside = str(self.task / "credentials" / "servercerts")
        self.assertTrue(admission.value_admitted(CERT_DIR, inside, entry, self.task))
        self.assertFalse(
            admission.value_admitted(CERT_DIR, "/etc/ssl/certs", entry, self.task)
        )

    def test_negative_control_a_pinned_ssl_cert_dir_refuses_the_run(self):
        entry = tofu(CREDENTIALS)
        mutant = entry._replace(pinned=entry.pinned | {CERT_DIR: None})
        inside = str(self.task / "credentials" / "servercerts")
        self.assertFalse(admission.value_admitted(CERT_DIR, inside, mutant, self.task))


if __name__ == "__main__":
    unittest.main()
