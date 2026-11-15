from __future__ import annotations

import ssl
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from tests.utils.connect_proxy import ConnectProxy, direct_dials, recorded_dials
from tests.utils.openbao_stub import OpenBaoStub, make_ca
from utils.openbao_client import (
    OpenBaoClient,
    OpenBaoError,
    Reference,
    https_connection,
    parse_reference,
    references,
    tls_context,
)

TOKEN = "s.deploy-token"
VALUE = "known-secret-value-4711"


class TestTheClientVerifiesTls(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stub = OpenBaoStub(tokens={TOKEN: ["tenant/"]}, logins={})
        cls.stub.put("tenant/ws-a/ssh", {"private_key": VALUE})
        cls._other = tempfile.TemporaryDirectory()
        _, other_ca = make_ca("another CA")
        cls.other_cafile = str(Path(cls._other.name) / "other.pem")
        Path(cls.other_cafile).write_bytes(
            other_ca.public_bytes(serialization.Encoding.PEM)
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stub.close()
        cls._other.cleanup()

    def read(self, cafile: str | None) -> str:
        client = OpenBaoClient(self.stub.addr, cafile, TOKEN)
        return client.read(Reference("tenant", "ws-a/ssh", "private_key"))

    def test_the_client_verifies_tls(self) -> None:
        self.assertEqual(self.read(self.stub.cafile), VALUE)
        for cafile in (None, self.other_cafile):
            with self.subTest(cafile=cafile), self.assertRaises(OpenBaoError) as caught:
                self.read(cafile)
            self.assertIn("TLS verification failed", str(caught.exception))

    def test_the_context_checks_the_chain_and_the_host_name(self) -> None:
        context = tls_context(self.stub.cafile)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_the_deployment_ca_extends_the_system_store(self) -> None:
        system = len(tls_context(None).get_ca_certs())
        self.assertEqual(len(tls_context(self.stub.cafile).get_ca_certs()), system + 1)

    def test_a_plain_http_address_is_refused(self) -> None:
        with self.assertRaises(OpenBaoError):
            OpenBaoClient(self.stub.addr.replace("https://", "http://"), None, TOKEN)

    def test_a_failure_names_the_path_and_the_field_but_never_the_value(self) -> None:
        client = OpenBaoClient(self.stub.addr, self.stub.cafile, TOKEN)
        for reference in (
            Reference("tenant", "ws-a/missing", "private_key"),
            Reference("tenant", "ws-a/ssh", "public_key"),
            Reference("platform", "store/semaphore", "token"),
        ):
            with (
                self.subTest(reference=str(reference)),
                self.assertRaises(OpenBaoError) as caught,
            ):
                client.read(reference)
            message = str(caught.exception)
            self.assertIn(f"{reference.mount}/{reference.path}", message)
            self.assertIn(reference.field, message)
            self.assertNotIn(VALUE, message)

    def test_create_only_never_overwrites(self) -> None:
        client = OpenBaoClient(self.stub.addr, self.stub.cafile, TOKEN)
        self.assertTrue(client.write_create_only("tenant", "ws-a/new", {"v": "1"}))
        self.assertFalse(client.write_create_only("tenant", "ws-a/new", {"v": "2"}))
        self.assertEqual(self.stub.kv["tenant/ws-a/new"], [{"v": "1"}])

    def test_write_adds_a_version_and_a_denied_path_fails(self) -> None:
        client = OpenBaoClient(self.stub.addr, self.stub.cafile, TOKEN)
        client.write("tenant", "ws-a/rotated", {"v": "1"})
        client.write("tenant", "ws-a/rotated", {"v": "2"})
        self.assertEqual(self.stub.kv["tenant/ws-a/rotated"], [{"v": "1"}, {"v": "2"}])
        with self.assertRaises(OpenBaoError) as caught:
            client.write("platform", "store/other", {"v": VALUE})
        self.assertIn(
            "platform/store/other could not be written (HTTP 403)",
            str(caught.exception),
        )
        self.assertNotIn(VALUE, str(caught.exception))


class TestTheClientBehindTheEgressProxy(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stub = OpenBaoStub(tokens={TOKEN: ["tenant/"]}, logins={})
        cls.stub.put("tenant/ws-a/ssh", {"private_key": VALUE})
        cls.target = cls.stub.addr.removeprefix("https://")
        cls.proxy = ConnectProxy(refused=("127.0.0.2:1",))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.proxy.close()
        cls.stub.close()

    def read(self, addr: str, proxy: str | None) -> tuple[str, list[str], list[str]]:
        """
        Args:
            addr: the OpenBao address the client gets.
            proxy: the ``EGRESS_PROXY`` it gets.

        Returns:
            The value read, every dial of the client and every target the
            proxy was asked for meanwhile.
        """
        asked = len(self.proxy.targets)
        with recorded_dials() as dials:
            client = OpenBaoClient(addr, self.stub.cafile, TOKEN, proxy=proxy)
            value = client.read(Reference("tenant", "ws-a/ssh", "private_key"))
        return value, dials, self.proxy.targets[asked:]

    def test_a_proxied_client_reaches_openbao_through_a_connect_tunnel(self) -> None:
        value, dials, targets = self.read(self.stub.addr, self.proxy.address)
        self.assertEqual(value, VALUE)
        self.assertEqual(targets, [self.target])
        self.assertEqual(direct_dials(dials, self.proxy.address), [])
        self.assertEqual(self.stub.requests[-1][1], "tenant/data/ws-a/ssh")

    def test_a_client_without_a_proxy_connects_directly(self) -> None:
        value, dials, targets = self.read(self.stub.addr, None)
        self.assertEqual(value, VALUE)
        self.assertEqual(targets, [])
        self.assertEqual(dials, [self.target])

    def test_the_tunnel_checks_the_certificate_against_the_openbao_name(self) -> None:
        addr = self.stub.addr.replace("127.0.0.1", "localhost")
        with self.assertRaises(OpenBaoError) as caught:
            self.read(addr, self.proxy.address)
        self.assertIn("TLS verification failed", str(caught.exception))

    def test_a_refused_tunnel_fails_the_request(self) -> None:
        with self.assertRaises(OpenBaoError) as caught:
            self.read("https://127.0.0.2:1", self.proxy.address)
        self.assertIn("unreachable", str(caught.exception))

    def test_negative_control_a_direct_connection_beside_the_proxy_is_detected(
        self,
    ) -> None:
        def direct(host, port, context, timeout, proxy=None):
            return https_connection(host, port, context, timeout)

        with mock.patch("utils.openbao_client.https_connection", direct):
            value, dials, targets = self.read(self.stub.addr, self.proxy.address)
        self.assertEqual(value, VALUE)
        self.assertEqual(targets, [])
        self.assertEqual(direct_dials(dials, self.proxy.address), [self.target])


class TestTheTreeWalk(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stub = OpenBaoStub(tokens={TOKEN: ["tenant/ws-a/"]}, logins={})
        cls.stub.put("tenant/ws-a/ssh", {"private_key": VALUE, "user": "deploy"})
        cls.stub.put("tenant/ws-a/db/app/password", {"value": VALUE})
        cls.stub.put("tenant/ws-ab/x", {"value": VALUE})
        cls.client = OpenBaoClient(cls.stub.addr, cls.stub.cafile, TOKEN)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.stub.close()

    def test_the_tree_walk_lists_every_secret_below_the_folder(self) -> None:
        self.assertEqual(
            sorted(self.client.list_tree("tenant", "ws-a/")), ["db/app/password", "ssh"]
        )
        self.assertEqual(self.client.list_tree("tenant", "ws-a/empty/"), [])

    def test_a_denied_listing_fails(self) -> None:
        with self.assertRaises(OpenBaoError) as caught:
            self.client.list_tree("tenant", "ws-b/")
        self.assertIn("403", str(caught.exception))

    def test_read_all_answers_every_field(self) -> None:
        self.assertEqual(
            self.client.read_all("tenant", "ws-a/ssh"),
            {"private_key": VALUE, "user": "deploy"},
        )


class TestTheReference(unittest.TestCase):
    def test_a_reference_names_mount_path_and_field(self) -> None:
        self.assertEqual(
            parse_reference({"openbao": "tenant/ws-a/ssh#private_key"}, "app.ssh"),
            Reference("tenant", "ws-a/ssh", "private_key"),
        )

    def test_other_values_are_no_reference(self) -> None:
        for value in ("plain", 42, None, {"key": "x"}, ["openbao"]):
            with self.subTest(value=value):
                self.assertIsNone(parse_reference(value, "app.x"))

    def test_a_malformed_reference_names_the_credential(self) -> None:
        for value in (
            {"openbao": "tenant/ws-a/ssh"},
            {"openbao": "tenant#field"},
            {"openbao": "tenant/ws-a/../ws-b/ssh#key"},
            {"openbao": "tenant/ws-a/ssh#key", "extra": "x"},
            {"openbao": 42},
        ):
            with self.subTest(value=value), self.assertRaises(OpenBaoError) as caught:
                parse_reference(value, "web-app-x.secrets.credentials.ssh")
            self.assertIn("web-app-x.secrets.credentials.ssh", str(caught.exception))

    def test_nested_references_are_found_with_their_names(self) -> None:
        credentials = {
            "plain": "x",
            "ssh": {"openbao": "tenant/ws-a/ssh#private_key"},
            "recaptcha": {"key": "k", "secret": {"openbao": "tenant/ws-a/rc#secret"}},
        }
        self.assertEqual(
            list(references(credentials)),
            [
                ("ssh", Reference("tenant", "ws-a/ssh", "private_key")),
                ("recaptcha.secret", Reference("tenant", "ws-a/rc", "secret")),
            ],
        )


if __name__ == "__main__":
    unittest.main()
