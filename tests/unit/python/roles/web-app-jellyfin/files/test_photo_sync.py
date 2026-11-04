import base64
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-jellyfin" / "files" / "python" / "photo_sync.py"
)
LDAP_CLIENT = (
    PROJECT_ROOT
    / "roles"
    / "svc-db-openldap"
    / "files"
    / "python"
    / "ldap"
    / "client.py"
)
PHOTO = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x80, 0x00])
LDAP = {
    "uri": "ldap://127.0.0.1:389",
    "users_dn": "ou=users,dc=example,dc=org",
    "roles_dn": "ou=roles,dc=example,dc=org",
    "attributes": {"id": "uid", "mail": "mail", "name": "cn", "member_of": "memberOf"},
}


def load_module():
    if "ldap_client" not in sys.modules:
        sys.modules["ldap_client"] = types.ModuleType("ldap_client")
        exec(
            compile(read_text(str(LDAP_CLIENT)), str(LDAP_CLIENT), "exec"),
            sys.modules["ldap_client"].__dict__,
        )
    module = types.ModuleType("jellyfin_photo_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


class FakeDirectory:
    def __init__(self, entries):
        self.entries = entries
        self.closed = False

    def search(self, base, scope, search_filter, attributes):
        return self.entries

    def close(self):
        self.closed = True


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeJellyfin:
    def __init__(self, users):
        self.users = users
        self.uploads = []
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if request.full_url.endswith("/Users/AuthenticateByName"):
            return FakeResponse(json.dumps({"AccessToken": "tok"}).encode())
        if request.full_url.endswith("/Users"):
            return FakeResponse(json.dumps(self.users).encode())
        self.uploads.append(
            (request.full_url, request.get_header("Content-type"), request.data)
        )
        return FakeResponse(b"")


class JellyfinPhotoSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.environ = {
            "RBAC_SYNC_LDAP": json.dumps(LDAP),
            "LDAP_PHOTO_ATTRIBUTE": "jpegPhoto",
            "JELLYFIN_API": "http://127.0.0.1:8096",
            "JELLYFIN_API_CLIENT": 'MediaBrowser Client="infinito"',
            "JELLYFIN_ADMIN_USERNAME": "platformadmin",
            "JELLYFIN_ADMIN_PASSWORD": "secret",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, jellyfin, entries):
        directory = FakeDirectory(entries)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(
                self.environ,
                opener=jellyfin,
                connect=lambda uri: directory,
                state_file=self.state,
            )
        return stdout.getvalue().splitlines(), directory

    def entry(self, username, photo):
        return (
            f"uid={username}",
            {
                "uid": [username],
                "jpegphoto": [photo.decode("utf-8", "surrogateescape")],
            },
        )

    def test_a_directory_photo_is_pushed_base64_once(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])

        first, directory = self.run_main(jellyfin, [self.entry("biber", PHOTO)])
        second, _ = self.run_main(jellyfin, [self.entry("biber", PHOTO)])

        self.assertEqual(first, ["CHANGED biber photo"])
        self.assertEqual(second, ["UNCHANGED"])
        self.assertEqual(
            jellyfin.uploads,
            [
                (
                    "http://127.0.0.1:8096/UserImage?userId=u-1",
                    "image/jpeg",
                    base64.b64encode(PHOTO),
                )
            ],
        )
        self.assertTrue(directory.closed)

    def test_a_changed_photo_is_pushed_again(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        self.run_main(jellyfin, [self.entry("biber", PHOTO)])

        output, _ = self.run_main(jellyfin, [self.entry("biber", PHOTO + b"\x01")])

        self.assertEqual(output, ["CHANGED biber photo"])
        self.assertEqual(len(jellyfin.uploads), 2)

    def test_a_directory_account_without_a_jellyfin_user_is_skipped(self):
        jellyfin = FakeJellyfin([{"Name": "other", "Id": "u-2"}])

        output, _ = self.run_main(jellyfin, [self.entry("biber", PHOTO)])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(jellyfin.uploads, [])

    def test_the_admin_token_authorises_every_api_call(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        self.run_main(jellyfin, [self.entry("biber", PHOTO)])

        for request in jellyfin.requests[1:]:
            self.assertEqual(
                request.get_header("Authorization"), 'MediaBrowser Token="tok"'
            )


if __name__ == "__main__":
    unittest.main()
