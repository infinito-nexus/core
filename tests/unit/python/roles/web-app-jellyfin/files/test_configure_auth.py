import re
import subprocess
import unittest

from utils import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/web-app-jellyfin/files/shell/configure-auth.sh"

AUTH_RESPONSE = (
    '{"User":{"Name":"administrator","ServerId":"e5c","Id":"a1b2c3d4",'
    '"HasPassword":true,"Configuration":{"PlayDefaultAudioTrack":true},'
    '"Policy":{"IsAdministrator":true}},"SessionInfo":{"Id":"s1"},'
    '"AccessToken":"tok-abc-123","ServerId":"e5c"}'
)

_SED = re.compile(r"sed -n '(s/\.\*\"(?:AccessToken|User)\".*?/p)'")


def _apply(expression: str, payload: str) -> str:
    done = subprocess.run(
        ["sed", "-n", expression],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class TestConfigureAuthExtraction(unittest.TestCase):
    """One AuthenticateByName response must yield both the token and the user id.

    Authenticating twice with the fixed DeviceId in CLIENT_HDR makes Jellyfin
    revoke the first session, so the token from an earlier call is already dead
    when the password change presents it.
    """

    def setUp(self) -> None:
        self.source = SCRIPT.read_text()
        self.expressions = _SED.findall(self.source)

    def test_the_script_keeps_exactly_one_authenticate_call_site_per_field(self):
        self.assertEqual(self.source.count("Users/AuthenticateByName"), 1)

    def test_one_response_yields_both_the_token_and_the_user_id(self):
        self.assertEqual(len(self.expressions), 2)
        extracted = {_apply(expression, AUTH_RESPONSE) for expression in self.expressions}
        self.assertEqual(extracted, {"tok-abc-123", "a1b2c3d4"})

    def test_a_response_without_a_token_extracts_nothing(self):
        for expression in self.expressions:
            with self.subTest(expression=expression):
                self.assertEqual(_apply(expression, '{"Error":"Unauthorized"}'), "")


if __name__ == "__main__":
    unittest.main()
