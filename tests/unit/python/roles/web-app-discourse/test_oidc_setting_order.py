from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text

CONFIG = PROJECT_ROOT / "roles/web-app-discourse/templates/config.yml.j2"
PREREQUISITES = (
    "openid_connect_discovery_document",
    "openid_connect_client_id",
    "openid_connect_client_secret",
)


def _line_of(lines: list[str], setting: str) -> int:
    return next(
        index
        for index, line in enumerate(lines)
        if f'rails r "SiteSetting.{setting} = ' in line
    )


class TestDiscourseOidcSettingOrder(unittest.TestCase):
    def test_oidc_is_enabled_only_after_its_prerequisites_are_set(self) -> None:
        lines = read_text(str(CONFIG)).splitlines()
        enable = _line_of(lines, "openid_connect_enabled")
        for setting in PREREQUISITES:
            with self.subTest(setting=setting):
                self.assertLess(
                    _line_of(lines, setting),
                    enable,
                    "Discourse rejects openid_connect_enabled = true on a fresh "
                    "database until the discovery document, client ID and client "
                    "secret are set",
                )


if __name__ == "__main__":
    unittest.main()
