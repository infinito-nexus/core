from __future__ import annotations

import unittest

from .test_backchannel_tls import render_env

BACKCHANNEL_RESPONSES = "org.keycloak.services.managers.ResourceAdminManager:debug"


def logs_every_backchannel_response(env: dict[str, str]) -> bool:
    """Tell whether Keycloak logs the answer of every back-channel logout call.

    Args:
        env: keys and values of Keycloak's rendered env file.

    Returns:
        True when KC_LOG_LEVEL keeps the root category at INFO and sets the
        ResourceAdminManager category to debug.
    """
    if "KC_LOG_LEVEL" not in env:
        return False
    root, *categories = env["KC_LOG_LEVEL"].split(",")
    return root == "INFO" and BACKCHANNEL_RESPONSES in categories


class TestKeycloakLogsEveryBackchannelResponse(unittest.TestCase):
    def test_every_deploy_logs_the_answer_of_each_backchannel_call(self) -> None:
        for debug in (False, True):
            with self.subTest(debug=debug):
                self.assertTrue(
                    logs_every_backchannel_response(
                        render_env(ca_injected=False, debug=debug)
                    )
                )

    def test_a_missing_or_unreachable_category_is_caught(self) -> None:
        for env in (
            {},
            {"KC_LOG_LEVEL": "INFO"},
            {"KC_LOG_LEVEL": f"DEBUG,{BACKCHANNEL_RESPONSES}"},
            {
                "KC_LOG_LEVEL": "INFO",
                "KC_LOG_LEVEL_ORG_KEYCLOAK_SERVICES_MANAGERS_RESOURCEADMINMANAGER": "DEBUG",
            },
        ):
            with self.subTest(env=env):
                self.assertFalse(logs_every_backchannel_response(env))


if __name__ == "__main__":
    unittest.main()
