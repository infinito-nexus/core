from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.vault import VaultLib, VaultSecret
from ruamel.yaml.comments import TaggedScalar

from cli.administration.inventory.gateway.__main__ import main
from cli.administration.inventory.ruamel_io import (
    dump_document,
    load_document,
)

GATEWAY = "echoserver"
GALAXY = "galaxyserver"
HOTEL = "hotelserver"
ADDRESSES = {GATEWAY: "10.100.0.1", GALAXY: "10.100.0.2", HOTEL: "10.100.0.3"}
MODEL = "mock/deterministic"
DEFAULT_PASSWORD = "gateway-pass-default"
HOTEL_PASSWORD = "gateway-pass-hotel"
MASTER_KEY = "sk-master-of-the-gateway-0123456789"


def _interface(host: str) -> dict:
    peers = [
        {"host": other, "address": address, "is_hub": other == GATEWAY}
        for other, address in ADDRESSES.items()
        if other != host and GATEWAY in (host, other)
    ]
    return {
        "name": "mesh0",
        "host": host,
        "address": ADDRESSES[host],
        "primary": True,
        "is_hub": host == GATEWAY,
        "peers": peers,
    }


def _litellm(document) -> dict:
    return document.get("applications", {}).get("svc-ai-litellm", {})


def _credentials(document) -> dict:
    return _litellm(document).get("secrets", {}).get("credentials", {})


def _service(document) -> dict:
    return _litellm(document).get("services", {}).get("litellm", {})


def _raw(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def _decrypt(value, password: str) -> str:
    assert isinstance(value, TaggedScalar), value
    vault = VaultLib([("default", VaultSecret(password.encode()))])
    return vault.decrypt(str(value.value)).decode()


class TestGatewayPass(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.host_vars = root / "host_vars"
        self.host_vars.mkdir()
        inventories = {
            GATEWAY: "svc-ai-litellm",
            GALAXY: "web-app-openwebui",
            HOTEL: "web-app-hermes",
        }
        self.inventories = []
        for host, group in inventories.items():
            path = root / f"{host}-devices.yml"
            path.write_text(
                f"all:\n  children:\n    {group}:\n      hosts:\n        {host}: {{}}\n",
                encoding="utf-8",
            )
            self.inventories.append(path)
            applications = {
                "svc-net-wireguard": {"networks": {"interfaces": [_interface(host)]}}
            }
            if host == GATEWAY:
                applications["svc-ai-litellm"] = {
                    "secrets": {"credentials": {"master_key": MASTER_KEY}}
                }
            else:
                applications["svc-ai-litellm"] = {
                    "services": {"litellm": {"gateway_host": GATEWAY}}
                }
            dump_document(
                self.host_vars / f"{host}.yml", {"applications": applications}
            )
        self.default_password = root / ".password"
        self.default_password.write_text(DEFAULT_PASSWORD + "\n", encoding="utf-8")
        self.hotel_password = root / ".password-hotel"
        self.hotel_password.write_text(HOTEL_PASSWORD + "\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra: str) -> tuple[int, str]:
        argv = []
        for path in self.inventories:
            argv += ["--inventory", str(path)]
        argv += [
            "--host-vars-dir",
            str(self.host_vars),
            "--vault-password-file",
            str(self.default_password),
            "--host-vault-password-file",
            f"{HOTEL}={self.hotel_password}",
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue() + err.getvalue()

    def _doc(self, host: str):
        return load_document(self.host_vars / f"{host}.yml")

    def _bytes(self) -> dict[str, bytes]:
        return {path.name: _raw(path) for path in sorted(self.host_vars.glob("*.yml"))}

    def _file(self, host: str) -> bytes:
        return _raw(self.host_vars / f"{host}.yml")

    def _held_key(self, consumer: str, password: str) -> str:
        return _decrypt(_credentials(self._doc(consumer))["gateway_key"], password)

    def _gateway_key(self, consumer: str) -> str:
        return _decrypt(
            _credentials(self._doc(GATEWAY))["host_keys"][consumer], DEFAULT_PASSWORD
        )

    def test_first_pass_writes_both_halves_of_every_key(self):
        code, output = self._run("--chat-model", f"{GATEWAY}={MODEL}")
        self.assertEqual(code, 0, output)
        for consumer, password in ((GALAXY, DEFAULT_PASSWORD), (HOTEL, HOTEL_PASSWORD)):
            with self.subTest(consumer=consumer):
                service = _service(self._doc(consumer))
                self.assertEqual(service["gateway_url"], "http://10.100.0.1:8081")
                self.assertEqual(service["gateway_model"], MODEL)
                held = self._held_key(consumer, password)
                self.assertTrue(held.startswith("sk-"))
                self.assertEqual(held, self._gateway_key(consumer))
        self.assertNotEqual(self._gateway_key(GALAXY), self._gateway_key(HOTEL))

    def test_a_host_with_its_own_vault_password_is_encrypted_with_it(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        with self.assertRaises(AnsibleError):
            self._held_key(HOTEL, DEFAULT_PASSWORD)
        self.assertTrue(self._held_key(HOTEL, HOTEL_PASSWORD))

    def test_a_rerun_changes_no_file(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        before = self._bytes()
        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn("0 host_vars written", output)
        self.assertEqual(before, self._bytes())

    def test_rotation_replaces_the_key_of_the_named_host_only(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        galaxy_before = self._held_key(GALAXY, DEFAULT_PASSWORD)
        hotel_bytes = self._file(HOTEL)
        hotel_entry = str(_credentials(self._doc(GATEWAY))["host_keys"][HOTEL].value)
        code, output = self._run("--rotate", GALAXY)
        self.assertEqual(code, 0, output)
        galaxy_after = self._held_key(GALAXY, DEFAULT_PASSWORD)
        self.assertNotEqual(galaxy_before, galaxy_after)
        self.assertEqual(galaxy_after, self._gateway_key(GALAXY))
        self.assertEqual(hotel_bytes, self._file(HOTEL))
        self.assertEqual(
            hotel_entry, str(_credentials(self._doc(GATEWAY))["host_keys"][HOTEL].value)
        )

    def test_rotating_a_host_that_consumes_nothing_is_refused(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        code, output = self._run("--rotate", GATEWAY)
        self.assertEqual(code, 1)
        self.assertIn(GATEWAY, output)

    def test_removing_the_value_drops_the_host_on_both_sides(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        galaxy_bytes = self._file(GALAXY)
        document = self._doc(HOTEL)
        _service(document)["gateway_host"] = ""
        dump_document(self.host_vars / f"{HOTEL}.yml", document)
        code, output = self._run()
        self.assertEqual(code, 0, output)
        hotel = self._doc(HOTEL)
        self.assertNotIn("gateway_url", _service(hotel))
        self.assertNotIn("gateway_model", _service(hotel))
        self.assertNotIn("gateway_key", _credentials(hotel))
        self.assertEqual(
            sorted(_credentials(self._doc(GATEWAY))["host_keys"]), [GALAXY]
        )
        self.assertEqual(galaxy_bytes, self._file(GALAXY))
        self.assertIn(f"{GATEWAY}: dropped the key of {HOTEL}", output)

    def test_a_missing_mesh_address_names_both_hosts(self):
        document = self._doc(GATEWAY)
        document["applications"]["svc-net-wireguard"]["networks"]["interfaces"] = []
        dump_document(self.host_vars / f"{GATEWAY}.yml", document)
        before = self._bytes()
        code, output = self._run("--chat-model", f"{GATEWAY}={MODEL}")
        self.assertEqual(code, 1)
        self.assertIn(GALAXY, output)
        self.assertIn(GATEWAY, output)
        self.assertIn("no mesh address", output)
        self.assertEqual(before, self._bytes())

    def test_a_consuming_host_never_receives_the_master_key(self):
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        for consumer in (GALAXY, HOTEL):
            with self.subTest(consumer=consumer):
                text = self._file(consumer).decode()
                self.assertNotIn(MASTER_KEY, text)
                self.assertNotIn("master_key", text)
                self.assertEqual(
                    sorted(_credentials(self._doc(consumer))), ["gateway_key"]
                )

    def test_without_a_chat_model_the_pass_writes_nothing(self):
        before = self._bytes()
        code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("--chat-model", output)
        self.assertEqual(before, self._bytes())

    def test_a_gateway_host_that_names_a_gateway_is_refused(self):
        document = self._doc(GATEWAY)
        document["applications"]["svc-ai-litellm"]["services"] = {
            "litellm": {"gateway_host": GALAXY}
        }
        dump_document(self.host_vars / f"{GATEWAY}.yml", document)
        code, output = self._run("--chat-model", f"{GATEWAY}={MODEL}")
        self.assertEqual(code, 1)
        self.assertIn("runs its own gateway", output)

    def test_the_gateway_port_override_reaches_the_url(self):
        document = self._doc(GATEWAY)
        document["applications"]["svc-ai-litellm"]["services"] = {
            "litellm": {"ports": {"local": {"http": 9090}}}
        }
        dump_document(self.host_vars / f"{GATEWAY}.yml", document)
        self._run("--chat-model", f"{GATEWAY}={MODEL}")
        self.assertEqual(
            _service(self._doc(GALAXY))["gateway_url"], "http://10.100.0.1:9090"
        )


if __name__ == "__main__":
    unittest.main()
