from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-matomo"
PLUGIN = read_text(str(ROLE / "files" / "php" / "infinito_rbac_login.php"))
ID_TOKEN = "$_SESSION['loginoidc_idtoken']"


def _method(name: str) -> str:
    """
    Args:
        name: a method of the plugin class.

    Returns:
        The source of that method, from its signature to its closing brace.
    """
    start = PLUGIN.index(f"function {name}(")
    return PLUGIN[start : PLUGIN.index("\n    }\n", start)]


def _events() -> dict[str, str]:
    """
    Returns:
        The handler method of every event the plugin registers.
    """
    return dict(re.findall(r"'([\w.]+)' => '(\w+)'", _method("registerEvents")))


class TestTheRoleGroupsApplyAfterRebelOidcStoredTheToken(unittest.TestCase):
    def test_the_sign_in_event_never_applies_a_token(self):
        record = _method(_events()["Login.authenticate.successful"])
        for call in ("self::applyIdToken(", "self::groupsClaim("):
            self.assertNotIn(
                call,
                record,
                "Matomo fires Login.authenticate.successful inside "
                "SessionInitializer::initSession, and RebelOIDC stores the ID token in "
                "the session only after that call returned",
            )

    def test_the_sign_in_marks_the_token_already_in_the_session_as_applied(self):
        self.assertIn(
            f"$_SESSION[self::APPLIED_TOKEN_DIGEST] = hash('sha256', (string) ({ID_TOKEN} ?? ''));",
            _method(_events()["Login.authenticate.successful"]),
            "a callback that aborts before RebelOIDC stores its token leaves the "
            "previous sign-in's token in the session",
        )

    def test_the_next_request_applies_the_token(self):
        handler = _events()["Platform.initialized"]
        self.assertIn(ID_TOKEN, _method(handler))
        self.assertIn("self::applyIdToken(", _method(handler))

    def test_the_session_keeps_a_digest_never_the_token(self):
        self.assertIn(
            "$_SESSION[self::APPLIED_TOKEN_DIGEST] = hash('sha256', $idToken);",
            _method("applyRoleGroups"),
        )
        self.assertIsNone(re.search(r"\$_SESSION\[[^\]]+\] = \$idToken", PLUGIN))

    def test_only_a_rebeloidc_callback_binds_the_session(self):
        record = _method(_events()["Login.authenticate.successful"])
        self.assertLess(
            record.index("unset($_SESSION[self::SIGNED_IN_LOGIN]"),
            record.index("=== 'RebelOIDC'"),
            "a password sign-in in a session RebelOIDC signed in before keeps its "
            "ID token, so every sign-in has to drop the binding first",
        )
        self.assertIn("=== 'callback'", record)


if __name__ == "__main__":
    unittest.main()
