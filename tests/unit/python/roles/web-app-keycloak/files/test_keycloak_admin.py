import io
import json
import sys
import tempfile
import unittest
import unittest.mock as mock
import urllib.error
from pathlib import Path

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))

import keycloak_admin as m


class TestContainerCredentials(unittest.TestCase):
    def test_credentials_come_from_the_container_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            environ = Path(tmp) / "environ"
            environ.write_bytes(
                b"PATH=/bin\0KEYCLOAK_PERMANENT_ADMIN_USERNAME=admin\0"
                b"KEYCLOAK_PERMANENT_ADMIN_PASSWORD=a=b\0"
            )
            self.assertEqual(m.container_credentials(environ), ("admin", "a=b"))


class _Response(io.BytesIO):
    def __init__(self, body=b"", location=""):
        super().__init__(body)
        self.headers = {"Location": location} if location else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestKeycloakClient(unittest.TestCase):
    def test_one_token_serves_calls_until_it_nears_expiry(self):
        token = json.dumps({"access_token": "t", "expires_in": 300}).encode()
        calls = []

        def urlopen(request, timeout):
            calls.append(request.full_url)
            if request.full_url.endswith("/token"):
                return _Response(token)
            return _Response(b"", "http://kc/admin/realms/r/groups/new-id")

        kc = m.Keycloak("http://kc", "r", "admin", "pw")
        with mock.patch.object(m.urllib.request, "urlopen", urlopen):
            _, created = kc.call("POST", "groups/root/children", {"name": "x"})
            kc.call("GET", "groups/new-id")
        self.assertEqual(created, "new-id")
        self.assertEqual(sum(url.endswith("/token") for url in calls), 1)

    def test_realm_level_calls_reach_any_realm_with_the_same_token(self):
        token = json.dumps({"access_token": "t", "expires_in": 300}).encode()
        calls = []

        def urlopen(request, timeout):
            calls.append(request.full_url)
            if request.full_url.endswith("/token"):
                return _Response(token)
            return _Response(b"{}")

        kc = m.Keycloak("http://kc", "r", "admin", "pw")
        with mock.patch.object(m.urllib.request, "urlopen", urlopen):
            kc.call("GET", "clients")
            kc.admin("GET", "master")
        self.assertEqual(
            [url for url in calls if not url.endswith("/token")],
            ["http://kc/admin/realms/r/clients", "http://kc/admin/realms/master"],
        )
        self.assertEqual(sum(url.endswith("/token") for url in calls), 1)

    def test_an_http_error_names_the_status_but_not_the_body(self):
        token = json.dumps({"access_token": "t", "expires_in": 300}).encode()

        def urlopen(request, timeout):
            if request.full_url.endswith("/token"):
                return _Response(token)
            raise urllib.error.HTTPError(
                request.full_url, 409, "Conflict", {}, io.BytesIO(b"secret detail")
            )

        kc = m.Keycloak("http://kc", "r", "admin", "pw")
        with (
            mock.patch.object(m.urllib.request, "urlopen", urlopen),
            self.assertRaises(m.KeycloakError) as raised,
        ):
            kc.call("POST", "groups/root/children", {"name": "x"})
        self.assertIn("HTTP 409", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))

    def test_a_delete_carries_its_payload_and_a_read_carries_none(self):
        token = json.dumps({"access_token": "t", "expires_in": 300}).encode()
        bodies = []

        def urlopen(request, timeout):
            if request.full_url.endswith("/token"):
                return _Response(token)
            bodies.append((request.get_method(), request.data))
            return _Response(b"")

        kc = m.Keycloak("http://kc", "r", "admin", "pw")
        with mock.patch.object(m.urllib.request, "urlopen", urlopen):
            kc.call("DELETE", "users/u/role-mappings/clients/c", [{"name": "x"}])
            kc.call("DELETE", "users/u")
            kc.call("GET", "users/u")
        self.assertEqual(
            bodies,
            [("DELETE", b'[{"name": "x"}]'), ("DELETE", None), ("GET", None)],
        )

    def test_a_service_account_signs_in_to_its_own_realm(self):
        token = json.dumps({"access_token": "t", "expires_in": 300}).encode()
        calls = []

        def urlopen(request, timeout):
            calls.append((request.full_url, request.data))
            if request.full_url.endswith("/token"):
                return _Response(token)
            return _Response(b"{}")

        kc = m.ServiceAccount("http://kc", "r", "workspace-members", "s3cr3t")
        with mock.patch.object(m.urllib.request, "urlopen", urlopen):
            kc.call("GET", "organizations")
        url, form = calls[0]
        self.assertEqual(url, "http://kc/realms/r/protocol/openid-connect/token")
        self.assertEqual(
            sorted(form.decode().split("&")),
            [
                "client_id=workspace-members",
                "client_secret=s3cr3t",
                "grant_type=client_credentials",
            ],
        )
        self.assertEqual(calls[1][0], "http://kc/admin/realms/r/organizations")

    def test_a_service_account_never_packs_its_secret_into_a_password_grant(self):
        encoded = []
        urlencode = m.urllib.parse.urlencode

        def recording(fields, *args, **kwargs):
            encoded.append(dict(fields))
            return urlencode(fields, *args, **kwargs)

        with mock.patch.object(m.urllib.parse, "urlencode", recording):
            m.ServiceAccount("http://kc", "r", "workspace-members", "s3cr3t")
        self.assertEqual(
            encoded,
            [
                {
                    "client_id": "workspace-members",
                    "client_secret": "s3cr3t",
                    "grant_type": "client_credentials",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
