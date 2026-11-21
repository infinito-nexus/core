import base64
import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-jellyfin" / "files" / "python" / "photo_sync.py"
)
TASKS = (
    PROJECT_ROOT / "roles" / "web-app-jellyfin" / "tasks" / "utils" / "photo_sync.yml"
)
PHOTO = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x80, 0x00])


def load_module():
    module = types.ModuleType("jellyfin_photo_sync")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def member(username, photo):
    """Return one ``@users`` member as the runner hands it over.

    Args:
        username: the login.
        photo: the photo octets, empty for an account without one.
    """
    return {
        "username": username,
        "email": "",
        "name": "",
        "uuid": "",
        "attributes": {"jpegPhoto": base64.b64encode(photo).decode()},
    }


def curl_config(text):
    """Return the url, method, headers and body of one ``curl -K -`` config.

    Args:
        text: the config curl reads on standard input.
    """
    request = {"headers": {}, "data": None}
    for line in text.splitlines():
        key, _, value = line.partition(" = ")
        value = json.loads(value)
        if key == "header":
            name, _, header = value.partition(": ")
            request["headers"][name] = header
        elif key == "data-binary":
            request["data"] = value
        else:
            request[key] = value
    return request


class FakeJellyfin:
    def __init__(self, users):
        self.users = users
        self.uploads = []
        self.requests = []
        self.argvs = []

    def __call__(self, argv, **kwargs):
        self.argvs.append(argv)
        request = curl_config(kwargs["input"])
        self.requests.append(request)
        if request["url"].endswith("/Users/AuthenticateByName"):
            body = json.dumps({"AccessToken": "tok"})
        elif request["url"].endswith("/Users"):
            body = json.dumps(self.users)
        else:
            self.uploads.append(
                (request["url"], request["headers"]["Content-Type"], request["data"])
            )
            body = ""
        return types.SimpleNamespace(returncode=0, stdout=body, stderr="")


class JellyfinPhotoSyncTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state.json"
        self.members_file = Path(self.tmp.name) / "members.json"
        self.environ = {
            "RBAC_SYNC_MEMBERS_FILE": str(self.members_file),
            "LDAP_PHOTO_ATTRIBUTE": "jpegPhoto",
            "RBAC_SYNC_CONTAINER_BIN": "container",
            "RBAC_SYNC_CID": "cid-1",
            "JELLYFIN_API": "http://127.0.0.1:8096",
            "JELLYFIN_API_CLIENT": 'MediaBrowser Client="infinito"',
            "JELLYFIN_ADMIN_USERNAME": "platformadmin",
            "JELLYFIN_ADMIN_PASSWORD": "secret",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, jellyfin, members):
        self.members_file.write_text(json.dumps({"@users:jpegPhoto": members}))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.mod.main(self.environ, run=jellyfin, state_file=self.state)
        return stdout.getvalue().splitlines()

    def test_a_directory_photo_is_pushed_base64_once(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])

        first = self.run_main(jellyfin, [member("biber", PHOTO)])
        second = self.run_main(jellyfin, [member("biber", PHOTO)])

        self.assertEqual(first, ["CHANGED biber photo"])
        self.assertEqual(second, ["UNCHANGED"])
        self.assertEqual(
            jellyfin.uploads,
            [
                (
                    "http://127.0.0.1:8096/UserImage?userId=u-1",
                    "image/jpeg",
                    base64.b64encode(PHOTO).decode(),
                )
            ],
        )

    def test_a_changed_photo_is_pushed_again(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        self.run_main(jellyfin, [member("biber", PHOTO)])

        output = self.run_main(jellyfin, [member("biber", PHOTO + b"\x01")])

        self.assertEqual(output, ["CHANGED biber photo"])
        self.assertEqual(len(jellyfin.uploads), 2)

    def test_an_account_without_a_photo_is_left_alone(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])

        output = self.run_main(jellyfin, [member("biber", b"")])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(jellyfin.uploads, [])

    def test_a_member_without_attributes_counts_as_one_without_a_photo(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        legacy = {"username": "biber", "email": "", "name": "", "uuid": ""}

        output = self.run_main(jellyfin, [legacy])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(jellyfin.uploads, [])

    def test_a_directory_account_without_a_jellyfin_user_is_skipped(self):
        jellyfin = FakeJellyfin([{"Name": "other", "Id": "u-2"}])

        output = self.run_main(jellyfin, [member("biber", PHOTO)])

        self.assertEqual(output, ["UNCHANGED"])
        self.assertEqual(jellyfin.uploads, [])

    def test_the_hook_receives_only_the_accounts_that_hold_a_photo(self):
        include = load_yaml_any(str(TASKS))[0]["vars"]
        source = read_text(str(SCRIPT))

        self.assertEqual(
            include["rbac_sync_roles"], ["@users:{{ LDAP.USER.ATTRIBUTES.PHOTO }}"]
        )
        self.assertEqual(
            include["rbac_sync_attributes"], ["{{ LDAP.USER.ATTRIBUTES.PHOTO }}"]
        )
        self.assertEqual(include["rbac_sync_modules"], [])
        self.assertNotIn("ldap_client", source)

    def test_the_admin_token_authorises_every_api_call(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        self.run_main(jellyfin, [member("biber", PHOTO)])

        for request in jellyfin.requests[1:]:
            self.assertEqual(
                request["headers"]["Authorization"], 'MediaBrowser Token="tok"'
            )

    def test_every_call_runs_curl_inside_the_container_with_secrets_off_argv(self):
        jellyfin = FakeJellyfin([{"Name": "biber", "Id": "u-1"}])
        self.run_main(jellyfin, [member("biber", PHOTO)])

        self.assertEqual(len(jellyfin.argvs), 3)
        for argv in jellyfin.argvs:
            self.assertEqual(argv[:5], ["container", "exec", "-i", "cid-1", "curl"])
            self.assertNotIn("secret", " ".join(argv))
            self.assertNotIn("tok", " ".join(argv))
        self.assertEqual(
            json.loads(jellyfin.requests[0]["data"])["Pw"],
            "secret",
        )

    def test_a_refused_call_fails_loudly(self):
        def refused(argv, **kwargs):
            return types.SimpleNamespace(
                returncode=7, stdout="", stderr="Failed to connect"
            )

        self.members_file.write_text(json.dumps({"@users:jpegPhoto": []}))
        with self.assertRaises(SystemExit) as caught:
            self.mod.main(self.environ, run=refused, state_file=self.state)
        self.assertIn("curl exited 7", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
