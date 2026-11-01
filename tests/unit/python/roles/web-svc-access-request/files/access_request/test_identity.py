from __future__ import annotations

import base64
import importlib
import json
import sys
import unittest

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

identity = importlib.import_module("access_request.identity")


def _token(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    return "e30." + payload.decode() + ".sig"


HEADERS = {
    "x-forwarded-access-token": _token({"sub": "sub-biber", "email": "b@x.org"}),
    "X-Forwarded-Preferred-Username": "biber",
    "X-Forwarded-Groups": "roles/web-app-a/user,/roles/web-app-b/editor",
}


class TestSessionPerson(unittest.TestCase):
    def test_the_requester_comes_from_the_gate_headers_and_the_token(self):
        person = identity.session_person(HEADERS)

        self.assertEqual("sub-biber", person.sub)
        self.assertEqual("biber", person.username)
        self.assertEqual("b@x.org", person.email)
        self.assertEqual(
            ("/roles/web-app-a/user", "/roles/web-app-b/editor"), person.groups
        )

    def test_a_request_without_a_forwarded_token_has_no_requester(self):
        with self.assertRaises(identity.IdentityError):
            identity.session_person({"X-Forwarded-Preferred-Username": "biber"})

    def test_a_token_without_a_subject_has_no_requester(self):
        with self.assertRaises(identity.IdentityError):
            identity.session_person(
                {**HEADERS, "x-forwarded-access-token": _token({"email": "b@x.org"})}
            )

    def test_a_token_that_is_no_jwt_has_no_requester(self):
        with self.assertRaises(identity.IdentityError):
            identity.session_person({**HEADERS, "x-forwarded-access-token": "opaque"})


class TestRequestForm(unittest.TestCase):
    def test_a_requester_field_in_the_form_is_ignored(self):
        form = identity.request_form(
            {
                "application": ["web-app-blog"],
                "roles": ["editor", " ", "subscriber"],
                "reason": ["write posts"],
                "requester": ["administrator"],
                "username": ["administrator"],
                "email": ["admin@example.org"],
            }
        )

        self.assertEqual(
            {
                "application": "web-app-blog",
                "roles": ["editor", "subscriber"],
                "reason": "write posts",
            },
            form,
        )

    def test_a_missing_field_reads_as_empty(self):
        self.assertEqual(
            {"application": "", "roles": [], "reason": ""}, identity.request_form({})
        )


if __name__ == "__main__":
    unittest.main()
