from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python"))
sys.path.insert(0, str(PROJECT_ROOT / "roles/web-app-keycloak/files/python/workspace"))

import invites as m
from workspaces import INVITE_PREFIX, PENDING_PREFIX

WS = "0f1e2d3c-4b5a-4968-8776-655443322110"
KEY = "77777777-7777-4777-8777-777777777777"
KEY2 = "88888888-8888-4888-8888-888888888888"
SECRET = "f" * 64
INVITEE = "newcomer@example.com"


class StagedCase(unittest.TestCase):
    def setUp(self) -> None:
        scratch = Path(self.enterContext(tempfile.TemporaryDirectory()))
        token = scratch / "token"
        token.write_text(SECRET, encoding="utf-8")
        self.env = {
            "BAO_ADDR": "https://openbao.example.com",
            "BAO_TOKEN_FILE": str(token),
        }


class TestStaged(StagedCase):
    def test_the_staged_invitation_comes_from_the_store_path_with_the_task_token(
        self,
    ) -> None:
        requests = []

        class Connection:
            def __init__(self, host, port, timeout, context):
                requests.append((host, port))

            def request(self, method, path, headers):
                requests.append((method, path, headers))

            def getresponse(self):
                response = mock.Mock(status=200)
                response.read.return_value = json.dumps(
                    {
                        "data": {
                            "data": {"email": " NewComer@Example.com", "role": "Admin"}
                        }
                    }
                ).encode()
                return response

            def close(self):
                return None

        with mock.patch.object(m.http.client, "HTTPSConnection", Connection):
            self.assertEqual(m.staged(self.env, WS, KEY), (INVITEE, "Admin"))
        self.assertEqual(
            requests,
            [
                ("openbao.example.com", 443),
                (
                    "GET",
                    f"/v1/platform/data/store/invites/{WS}/{KEY}",
                    {"X-Vault-Token": SECRET},
                ),
            ],
        )
        with self.assertRaises(ValueError):
            m.staged({**self.env, "BAO_ADDR": "http://openbao.example.com"}, WS, KEY)

    def test_the_staged_read_trusts_the_deployment_ca(self) -> None:
        cafiles = []

        def context(cafile=None):
            cafiles.append(cafile)
            raise OSError("stop before the request")

        with mock.patch.object(m.ssl, "create_default_context", context):
            for extra, expected in (
                ({"BAO_CACERT": "/etc/ca.pem"}, "/etc/ca.pem"),
                ({}, None),
            ):
                with self.subTest(cafile=expected), self.assertRaises(OSError):
                    m.staged({**self.env, **extra}, WS, KEY)
        self.assertEqual(cafiles, ["/etc/ca.pem", None])


class TestPendingKeys(unittest.TestCase):
    def test_a_recorded_key_moves_to_its_new_role_and_keeps_the_others(self) -> None:
        attributes = {PENDING_PREFIX + "Viewer": [KEY2, KEY]}
        m.record_key(attributes, KEY, "Admin", INVITEE)
        self.assertEqual(
            attributes,
            {
                PENDING_PREFIX + "Viewer": [KEY2],
                PENDING_PREFIX + "Admin": [KEY],
                INVITE_PREFIX + KEY: [INVITEE],
            },
        )

    def test_dropping_the_last_key_of_a_role_removes_its_listing(self) -> None:
        attributes = {"workspace.id": [WS]}
        m.record_key(attributes, KEY, "Admin", INVITEE)
        m.drop_key(attributes, KEY)
        self.assertEqual(attributes, {"workspace.id": [WS]})


class TestWriteAttributes(unittest.TestCase):
    def test_the_organization_goes_back_whole_with_the_edit(self) -> None:
        kc = mock.Mock()
        kc.call.side_effect = [
            ({"id": "o-1", "attributes": {"workspace.id": [WS]}}, ""),
            (None, ""),
        ]
        ws = mock.Mock(base="organizations/o-1")
        m.write_attributes(
            kc, ws, lambda attributes: m.record_key(attributes, KEY, "Admin", INVITEE)
        )
        written = {
            "id": "o-1",
            "attributes": {
                "workspace.id": [WS],
                PENDING_PREFIX + "Admin": [KEY],
                INVITE_PREFIX + KEY: [INVITEE],
            },
        }
        self.assertEqual(
            kc.call.call_args_list,
            [
                mock.call("GET", "organizations/o-1"),
                mock.call("PUT", "organizations/o-1", written),
            ],
        )
        self.assertEqual(ws.org, written)


if __name__ == "__main__":
    unittest.main()
