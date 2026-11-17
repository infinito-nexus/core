import socket
import ssl
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "svc-db-openldap"
    / "files"
    / "python"
    / "ldap"
    / "client.py"
)
USERS_DN = "ou=users,dc=example,dc=org"
BIBER_DN = "uid=biber,ou=users,dc=example,dc=org"


def load_module():
    module = types.ModuleType("ldap_client")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = bytearray(incoming)
        self.sent = bytearray()
        self.closed = False

    def recv(self, count):
        chunk = bytes(self.incoming[: min(count, 3)])
        del self.incoming[: len(chunk)]
        return chunk

    def sendall(self, data):
        self.sent.extend(data)

    def close(self):
        self.closed = True


class LdapClientTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def connection(self, incoming):
        connection = object.__new__(self.mod.Connection)
        connection.socket = FakeSocket(incoming)
        connection.message_id = 0
        return connection

    def response(self, message_id, operation):
        mod = self.mod
        return mod.tlv(mod.SEQUENCE, mod.number(mod.INTEGER, message_id) + operation)

    def done(self, code):
        mod = self.mod
        return mod.tlv(
            mod.SEARCH_RESULT_DONE,
            mod.number(mod.ENUMERATED, code) + mod.text("") + mod.text(""),
        )

    def test_bind_request_matches_the_ldapv3_encoding(self):
        mod = self.mod
        result = mod.number(mod.ENUMERATED, 0) + mod.text("") + mod.text("")
        connection = self.connection(
            self.response(1, mod.tlv(mod.BIND_RESPONSE, result))
        )

        self.assertEqual(connection.bind("cn=a", "p"), 0)
        self.assertEqual(
            bytes(connection.socket.sent),
            bytes.fromhex("30 11 02 01 01 60 0c 02 01 03 04 04 63 6e 3d 61 80 01 70"),
        )

    def test_bind_reports_invalid_credentials(self):
        mod = self.mod
        result = mod.number(mod.ENUMERATED, 49) + mod.text("") + mod.text("")
        connection = self.connection(
            self.response(1, mod.tlv(mod.BIND_RESPONSE, result))
        )

        self.assertEqual(connection.bind("cn=a", "wrong"), 49)

    def test_search_collects_entries_until_done(self):
        mod = self.mod
        attribute = mod.tlv(
            mod.SEQUENCE, mod.text("uid") + mod.tlv(0x31, mod.text("biber"))
        )
        found = mod.tlv(
            mod.SEARCH_RESULT_ENTRY,
            mod.text(BIBER_DN) + mod.tlv(mod.SEQUENCE, attribute),
        )
        connection = self.connection(
            self.response(1, found) + self.response(1, self.done(0))
        )

        entries = connection.search(
            USERS_DN, mod.SCOPE_ONE_LEVEL, mod.equality("uid", "biber"), ["uid"]
        )

        self.assertEqual(entries, [(BIBER_DN, {"uid": ["biber"]})])
        tag, content, _ = mod.decode(bytes(connection.socket.sent), 0)
        self.assertEqual(tag, mod.SEQUENCE)
        self.assertEqual(mod.children(content)[1][0], mod.SEARCH_REQUEST)

    def test_search_without_a_bind_sends_no_bind_request(self):
        mod = self.mod
        connection = self.connection(self.response(1, self.done(0)))

        connection.search(USERS_DN, mod.SCOPE_ONE_LEVEL, mod.present("uid"), [])

        _, content, _ = mod.decode(bytes(connection.socket.sent), 0)
        self.assertEqual(
            [tag for tag, _ in mod.children(content)], [mod.INTEGER, mod.SEARCH_REQUEST]
        )

    def test_search_raises_on_an_error_result(self):
        mod = self.mod
        connection = self.connection(self.response(1, self.done(32)))

        with self.assertRaises(mod.DirectoryError):
            connection.search(
                USERS_DN, mod.SCOPE_ONE_LEVEL, mod.present("objectClass"), []
            )

    def test_answers_to_other_messages_are_skipped(self):
        mod = self.mod
        connection = self.connection(
            self.response(7, self.done(32)) + self.response(1, self.done(0))
        )

        self.assertEqual(
            connection.search(USERS_DN, mod.SCOPE_ONE_LEVEL, mod.present("uid"), []),
            [],
        )

    def test_a_disconnection_notice_is_a_directory_error(self):
        mod = self.mod
        connection = self.connection(self.response(0, self.done(52)))

        with self.assertRaises(mod.DirectoryError):
            connection.search(USERS_DN, mod.SCOPE_ONE_LEVEL, mod.present("uid"), [])

    def test_add_values_matches_the_ldapv3_modify_encoding(self):
        mod = self.mod
        result = mod.number(mod.ENUMERATED, 0) + mod.text("") + mod.text("")
        connection = self.connection(
            self.response(1, mod.tlv(mod.MODIFY_RESPONSE, result))
        )

        self.assertEqual(connection.add_values("uid=b", {"mail": ["b@x"]}), 0)
        self.assertEqual(
            bytes(connection.socket.sent),
            bytes.fromhex(
                "30 22 02 01 01 66 1d 04 05 75 69 64 3d 62 30 14 30 12 0a 01 00"
                " 30 0d 04 04 6d 61 69 6c 31 05 04 03 62 40 78"
            ),
        )

    def test_add_values_reports_the_result_code(self):
        mod = self.mod
        result = mod.number(mod.ENUMERATED, 20) + mod.text("") + mod.text("")
        connection = self.connection(
            self.response(1, mod.tlv(mod.MODIFY_RESPONSE, result))
        )

        self.assertEqual(
            connection.add_values(BIBER_DN, {"objectClass": ["a"], "mail": ["b"]}),
            mod.TYPE_OR_VALUE_EXISTS,
        )

    def test_add_values_refuses_an_answer_to_another_operation(self):
        mod = self.mod
        connection = self.connection(self.response(1, self.done(0)))

        with self.assertRaises(mod.DirectoryError):
            connection.add_values(BIBER_DN, {"mail": ["b"]})

    def test_long_lengths_round_trip(self):
        mod = self.mod
        value = b"x" * 300
        encoded = mod.tlv(mod.OCTET_STRING, value)

        self.assertEqual(encoded[:4], bytes([mod.OCTET_STRING, 0x82, 0x01, 0x2C]))
        self.assertEqual(
            mod.decode(encoded, 0), (mod.OCTET_STRING, value, len(encoded))
        )

    def test_truncated_element_is_a_directory_error(self):
        mod = self.mod
        with self.assertRaises(mod.DirectoryError):
            mod.decode(bytes([mod.OCTET_STRING, 0x05, 0x61]), 0)

    def test_a_binary_value_survives_the_round_trip(self):
        mod = self.mod
        photo = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x80, 0xC3])
        attribute = mod.tlv(
            mod.SEQUENCE,
            mod.text("jpegPhoto") + mod.tlv(0x31, mod.tlv(mod.OCTET_STRING, photo)),
        )
        entry = mod.text(BIBER_DN) + mod.tlv(mod.SEQUENCE, attribute)

        _, values = mod.parse_entry(entry)

        self.assertEqual(mod.raw(values["jpegphoto"][0]), photo)

    def test_dn_comparison_ignores_case_and_spacing(self):
        self.assertEqual(
            self.mod.normalize_dn("CN=A, OU=Roles,dc=X"), "cn=a,ou=roles,dc=x"
        )

    def test_an_unsupported_uri_is_refused_before_connecting(self):
        with self.assertRaises(self.mod.DirectoryError):
            self.mod.Connection("http://openldap:389")


class RecordingContext(ssl.SSLContext):
    def wrap_socket(self, sock, server_hostname=None):
        self.wrapped = (sock, server_hostname)
        return sock


class LdapsConnectionTests(unittest.TestCase):
    def test_ldaps_raises_a_permissive_default_floor_to_tls_1_2(self):
        mod = load_module()
        context = RecordingContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        raw = object()

        with (
            mock.patch.object(mod.ssl, "create_default_context", return_value=context),
            mock.patch.object(mod.socket, "create_connection", return_value=raw),
        ):
            connection = mod.Connection("ldaps://openldap")

        self.assertIs(connection.socket, raw)
        self.assertEqual(context.wrapped, (raw, "openldap"))
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)


class LdapiConnectionTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        socket_path = Path(directory.name, "run", "ldapi")
        socket_path.parent.mkdir()
        self.path = str(socket_path)
        self.uri = "ldapi://" + quote(self.path, safe="")

    def listen(self):
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(self.path)
        server.listen(1)

    def test_an_ldapi_uri_connects_to_the_unix_socket_at_its_decoded_path(self):
        self.listen()

        connection = self.mod.Connection(self.uri)
        self.addCleanup(connection.close)

        self.assertEqual(connection.socket.family, socket.AF_UNIX)
        self.assertEqual(connection.socket.getpeername(), self.path)
        self.assertEqual(connection.socket.gettimeout(), self.mod.TIMEOUT_SECONDS)

    def test_a_missing_socket_says_which_socket_this_node_lacks(self):
        with self.assertRaises(self.mod.SocketMissingError) as raised:
            self.mod.Connection(self.uri)

        self.assertEqual(
            str(raised.exception), f"no directory socket at {self.path} on this node"
        )

    def test_a_socket_nobody_listens_on_is_refused(self):
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(self.path)
        stale.close()

        with self.assertRaises(ConnectionRefusedError):
            self.mod.Connection(self.uri)


if __name__ == "__main__":
    unittest.main()
