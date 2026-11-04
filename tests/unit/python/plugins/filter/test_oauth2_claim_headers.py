import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.oauth2_claim_headers import oauth2_claim_headers

ATTRIBUTES = {
    "USERNAME": "preferred_username",
    "NAME": "name",
    "EMAIL": "email",
    "PHONE_NUMBER": "phone_number",
    "ADDRESS": "address",
    "ZONEINFO": "zoneinfo",
}


class TestOauth2ClaimHeaders(unittest.TestCase):
    def test_a_declared_key_names_its_claim_and_headers(self):
        self.assertEqual(
            oauth2_claim_headers(ATTRIBUTES, ["NAME"]),
            [
                {
                    "key": "NAME",
                    "claim": "name",
                    "request": "X-Forwarded-Name",
                    "response": "X-Auth-Request-Name",
                    "variable": "upstream_http_x_auth_request_name",
                }
            ],
        )

    def test_a_multi_word_key_becomes_a_dashed_header(self):
        header = oauth2_claim_headers(ATTRIBUTES, ["PHONE_NUMBER"])[0]
        self.assertEqual(header["request"], "X-Forwarded-Phone-Number")
        self.assertEqual(
            header["variable"], "upstream_http_x_auth_request_phone_number"
        )

    def test_without_a_declaration_every_forwardable_key_is_listed(self):
        self.assertEqual(
            [header["key"] for header in oauth2_claim_headers(ATTRIBUTES)],
            ["NAME", "PHONE_NUMBER", "ZONEINFO"],
        )

    def test_identity_and_object_claims_are_refused(self):
        for key in ("USERNAME", "EMAIL", "ADDRESS", "BOGUS"):
            with self.subTest(key=key), self.assertRaises(AnsibleFilterError):
                oauth2_claim_headers(ATTRIBUTES, [key])

    def test_an_empty_declaration_forwards_nothing(self):
        self.assertEqual(oauth2_claim_headers(ATTRIBUTES, []), [])


if __name__ == "__main__":
    unittest.main()
