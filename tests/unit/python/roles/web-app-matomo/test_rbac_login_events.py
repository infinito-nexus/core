from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles" / "web-app-matomo"
PLUGIN = read_text(str(ROLE / "files" / "php" / "infinito_rbac_login.php"))


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


if __name__ == "__main__":
    unittest.main()
