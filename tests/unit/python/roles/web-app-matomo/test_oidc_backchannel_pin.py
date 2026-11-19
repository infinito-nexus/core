import re
import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles/web-app-matomo"
COMPOSE = read_text(str(ROLE / ROLE_FILE_TEMPL_COMPOSE))
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
SERVICE_START = "{% set service_name = MATOMO_SERVICE %}"
NEXT_SERVICE = re.compile(r"\{% set service_name = (?!MATOMO_SERVICE )")
PIN = "lookup('container_extra_hosts')"
SERVER_SIDE = {
    "exchange_url": "{{ OIDC.CLIENT.TOKEN_URL }}",
    "user_info_url": "{{ OIDC.CLIENT.USER_INFO_URL }}",
}


def _matomo_block():
    """Returns:
    The template lines of the matomo service, without the bootstrap service.
    """
    start = COMPOSE.index(SERVICE_START)
    end = NEXT_SERVICE.search(COMPOSE, start + len(SERVICE_START))
    return COMPOSE[start : end.start() if end else len(COMPOSE)]


class TestMatomoReachesTheProviderItCallsItself(unittest.TestCase):
    def test_rebeloidc_exchanges_the_code_and_reads_userinfo_server_side(self):
        oidc = SERVICES["matomo"]["oidc"]
        for key, endpoint in SERVER_SIDE.items():
            with self.subTest(key=key):
                self.assertEqual(oidc[key], endpoint)

    def test_the_sign_in_is_app_native_under_the_sso_gate_the_pin_reads(self):
        self.assertNotEqual(SERVICES["sso"].get("flavor"), "oauth2")
        self.assertIn("enabled", SERVICES["sso"])

    def test_the_matomo_container_pins_the_provider(self):
        self.assertIn(PIN, _matomo_block())


if __name__ == "__main__":
    unittest.main()
