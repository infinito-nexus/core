from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.administration.deploy.dedicated.openbao import OpenBaoPreflightError, prepare
from cli.administration.inventory.credentials import main
from tests.utils.openbao_stub import OpenBaoStub
from utils import openbao_client
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

APP = "app_test"
TOKEN = "s.operator-token"
TARGET = "tenant/ws-a"
SCHEMA = {
    "credentials": {
        "api_token": {"description": "API token", "algorithm": "alphanumeric"},
        "recaptcha": {
            "key": {"description": "site key", "algorithm": "alphanumeric"},
            "secret": {"description": "secret key", "algorithm": "alphanumeric"},
        },
    }
}


class TestGeneratedCredentialsGoToOpenBao(unittest.TestCase):
    def setUp(self) -> None:
        openbao_client._SESSION.clear()
        self.stub = OpenBaoStub(tokens={TOKEN: ["tenant/ws-a/"]}, logins={})
        self.addCleanup(self.stub.close)
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        self.role = root / "role"
        (self.role / "meta").mkdir(parents=True)
        (self.role / "vars").mkdir(parents=True)
        dump_yaml(str(self.role / ROLE_FILE_VARS_MAIN), {"application_id": APP})
        dump_yaml(
            str(self.role / ROLE_FILE_META_SERVICES),
            {"features": {"central_database": False}},
        )
        dump_yaml(str(self.role / ROLE_FILE_META_SECRETS), SCHEMA)
        self.inventory = root / "host_vars.yml"
        dump_yaml(str(self.inventory), {})

    def run_cli(self, *extra: str) -> tuple[int, str]:
        argv = [
            "credentials",
            "--role-path",
            str(self.role),
            "--inventory-file",
            str(self.inventory),
            "--openbao",
            TARGET,
            *extra,
        ]
        environ = {
            "BAO_ADDR": self.stub.addr,
            "BAO_CACERT": self.stub.cafile,
            "BAO_TOKEN": TOKEN,
            "SEMAPHORE_JWT": "",
            "BAO_ROLE": "",
        }
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.dict(os.environ, environ),
            mock.patch("subprocess.run") as vault,
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(output),
        ):
            status = main()
        vault.assert_not_called()
        return status, output.getvalue()

    def credentials(self) -> dict:
        return load_yaml_any(str(self.inventory))["applications"][APP]["secrets"][
            "credentials"
        ]

    def test_generated_credentials_are_written_create_only(self) -> None:
        status, output = self.run_cli()
        self.assertEqual(status, 0, output)
        self.assertEqual(
            self.credentials(),
            {
                "api_token": {"openbao": f"{TARGET}/{APP}/api_token#value"},
                "recaptcha": {
                    "key": {"openbao": f"{TARGET}/{APP}/recaptcha/key#value"},
                    "secret": {"openbao": f"{TARGET}/{APP}/recaptcha/secret#value"},
                },
            },
        )
        written = {path: versions[:] for path, versions in self.stub.kv.items()}
        self.assertEqual(
            sorted(written),
            [
                f"{TARGET}/{APP}/api_token",
                f"{TARGET}/{APP}/recaptcha/key",
                f"{TARGET}/{APP}/recaptcha/secret",
            ],
        )
        text = self.inventory.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        for versions in written.values():
            self.assertEqual(len(versions), 1)
            self.assertNotIn(versions[0]["value"], text)
            self.assertNotIn(versions[0]["value"], output)

        status, output = self.run_cli()
        self.assertEqual(status, 0, output)
        self.assertEqual(self.stub.kv, written)
        self.assertEqual(
            self.inventory.read_text(encoding="utf-8"),  # nocheck: cache-read tempdir
            text,
        )

    def test_an_existing_secret_keeps_its_version(self) -> None:
        self.stub.put(f"{TARGET}/{APP}/api_token", {"value": "kept"})
        status, output = self.run_cli()
        self.assertEqual(status, 0, output)
        self.assertEqual(self.stub.kv[f"{TARGET}/{APP}/api_token"], [{"value": "kept"}])
        self.assertEqual(
            self.credentials()["api_token"],
            {"openbao": f"{TARGET}/{APP}/api_token#value"},
        )

    def test_reference_mode_refuses_to_overwrite(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli("--force")
        self.assertEqual(self.stub.kv, {})

    def test_a_denied_write_fails_without_touching_the_inventory(self) -> None:
        before = self.inventory.read_text(encoding="utf-8")  # nocheck: cache-read
        with mock.patch(f"{__name__}.TARGET", "tenant/ws-b"):
            status, output = self.run_cli()
        self.assertEqual(status, 1)
        self.assertIn("HTTP 403", output)
        self.assertEqual(
            self.inventory.read_text(encoding="utf-8"),  # nocheck: cache-read tempdir
            before,
        )
        self.assertEqual(self.stub.kv, {})


class TestSuppliedCredentials(unittest.TestCase):
    def test_a_supplied_credential_must_exist(self) -> None:
        openbao_client._SESSION.clear()
        stub = OpenBaoStub(tokens={TOKEN: ["tenant/ws-a/"]}, logins={})
        self.addCleanup(stub.close)
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            (root / "host_vars").mkdir()
            (root / "host_vars" / "h.yml").write_text(
                "applications:\n  web-app-foo:\n    secrets:\n      credentials:\n"
                "        api_key: {openbao: tenant/ws-a/supplied/api_key#value}\n",
                encoding="utf-8",
            )
            inventory = root / "devices.yml"
            inventory.write_text("all: {}\n", encoding="utf-8")
            with self.assertRaises(OpenBaoPreflightError) as caught:
                prepare(
                    str(inventory),
                    {
                        "BAO_ADDR": stub.addr,
                        "BAO_CACERT": stub.cafile,
                        "BAO_TOKEN": TOKEN,
                    },
                )
        message = str(caught.exception)
        self.assertIn("tenant/ws-a/supplied/api_key", message)
        self.assertIn("web-app-foo.secrets.credentials.api_key", message)
        self.assertIn("HTTP 404", message)


if __name__ == "__main__":
    unittest.main()
