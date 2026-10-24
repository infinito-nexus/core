import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
