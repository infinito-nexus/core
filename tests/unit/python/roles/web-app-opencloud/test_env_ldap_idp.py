import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text

ENV = PROJECT_ROOT / "roles" / "web-app-opencloud" / "templates" / "env.j2"
LDAP_BLOCK = "{% if OPENCLOUD_LDAP_ENABLED | bool %}"


def _ldap_block() -> list[str]:
    lines = read_text(str(ENV)).splitlines()
    start = lines.index(LDAP_BLOCK)
    return lines[start + 1 : lines.index("{% endif %}", start)]


class TestBuiltinIdpOnTheDirectory(unittest.TestCase):
    def test_the_builtin_idp_drops_the_enabled_flag_the_schema_lacks(self) -> None:
        self.assertIn("IDP_USER_ENABLED_ATTRIBUTE=", _ldap_block())


if __name__ == "__main__":
    unittest.main()
