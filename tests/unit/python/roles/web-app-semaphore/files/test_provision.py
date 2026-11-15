from __future__ import annotations

import contextlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .provision._fake_provision import CREDENTIALS, STATE_KEYS, WORKSPACE, load

provision = load("provision")
RefusedError = provision.inputs.RefusedError


class TempCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)


class TestBackend(TempCase):
    def setUp(self):
        super().setUp()
        self.config = {"cafile": "", "state": "https://s3.example.org"}

    def test_values_are_escaped_for_hcl(self):
        self.assertEqual(provision._hcl('a${b}%{c}"'), '"a$${b}%%{c}\\""')

    def test_the_backend_file_is_private_and_written_once(self):
        keys = {**STATE_KEYS, "secret_key": "s${x}"}
        path = provision.write_backend(
            self.root, self.config, "b", "SO/1.tfstate", keys
        )
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        self.assertIn('secret_key = "s$${x}"\n', text)
        self.assertIn('endpoints = {\n  s3 = "https://s3.example.org"\n}\n', text)
        self.assertNotIn("custom_ca_bundle", text)
        with self.assertRaises(FileExistsError):
            provision.write_backend(self.root, self.config, "b", "k", keys)

    def test_a_ca_file_reaches_the_backend(self):
        config = {**self.config, "cafile": "/etc/ssl/ca.pem"}
        path = provision.write_backend(self.root, config, "b", "k", STATE_KEYS)
        text = path.read_text()  # nocheck: cache-read tempdir
        self.assertIn('custom_ca_bundle = "/etc/ssl/ca.pem"\n', text)


class TestEncryption(unittest.TestCase):
    def test_state_and_plan_are_enforced_with_the_workspace_transit_key(self):
        document = json.loads(provision.encryption(WORKSPACE))
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
        names = provision.credential_names(CREDENTIALS)
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


class TestProviderTokenIsolation(unittest.TestCase):
    def test_each_customer_token_lies_below_the_provision_role_only(self):
        own = f"tenant/data/{WORKSPACE}-provision/providers/"
        runner = f"tenant/data/{WORKSPACE}/"
        kind = provision.provider_env.WORKSPACE_SECRETS
        holders = {
            name: spec[kind]
            for name, spec in CREDENTIALS["providers"].items()
            if kind in spec
        }
        self.assertEqual(set(holders), {"hetzner", "ionos"})
        for name, secrets in holders.items():
            with self.subTest(provider=name):
                (secret,) = secrets
                path = secret["path"].format(workspace=WORKSPACE)
                self.assertEqual(path, own + name)
                self.assertFalse(path.startswith(runner))
                self.assertEqual(set(secret["env"].values()), {"token"})
                platform = {
                    env
                    for s in CREDENTIALS["providers"][name]["secrets"]
                    for env in s["env"]
                }
                self.assertEqual(set(secret["env"]), platform)


class TestLock(TempCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(provision.tempfile, "tempdir", str(self.root))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unlock_refuses_while_a_task_of_its_workspace_runs(self):
        with provision.workspace_lock(WORKSPACE, False):
            with provision.workspace_lock(WORKSPACE, False):
                pass
            with (
                self.assertRaisesRegex(RefusedError, "is running"),
                provision.workspace_lock(WORKSPACE, True),
            ):
                pass
            with provision.workspace_lock("ws-other", True):
                pass
        with provision.workspace_lock(WORKSPACE, True):
            pass

    def test_the_task_directory_is_removed_after_a_failure(self):
        with self.assertRaises(RuntimeError), provision.task_directory() as task:
            (task / "backend.tfbackend").write_text("x")
            raise RuntimeError("tofu failed")
        self.assertFalse(task.exists())


class TestMain(unittest.TestCase):
    def run_main(self, argv, env):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = provision.main(argv, env, Path("/nonexistent"))
        return code, stderr.getvalue()

    def test_a_bad_call_or_configuration_is_refused(self):
        valid = {
            "PROVISION_DNS_FLAVOR": "knot",
            "BAO_ADDR": "https://bao.example.org",
            "PROVISION_STATE_ENDPOINT": "https://s3.example.org",
        }
        cases = {
            "names no template": (["provision.py"], valid),
            "takes no argument": (["provision.py", "destroy", "x"], valid),
            "PROVISION_CATALOG_DIR is missing": (["provision.py", "destroy"], valid),
            "is no DNS flavor": (
                ["provision.py", "dns"],
                {**valid, "PROVISION_DNS_FLAVOR": "bind"},
            ),
        }
        for message, (argv, env) in cases.items():
            with self.subTest(message=message):
                code, stderr = self.run_main(argv, env)
                self.assertEqual(code, 2)
                self.assertIn("refused: ", stderr)
                self.assertIn(message, stderr)


if __name__ == "__main__":
    unittest.main()
