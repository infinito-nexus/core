import unittest

from jinja2 import ChainableUndefined, Environment, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text

ENV = PROJECT_ROOT / "roles" / "web-app-opencloud" / "templates" / "env.j2"
LDAP_BLOCK = "{% if OPENCLOUD_LDAP_ENABLED | bool %}"


def _ldap_env(enabled: bool) -> dict[str, str]:
    """
    Args:
        enabled: the value of ``OPENCLOUD_LDAP_ENABLED``.

    Returns:
        ``{key: value}`` the LDAP block of ``env.j2`` renders.
    """
    lines = read_text(str(ENV)).splitlines()
    start = lines.index(LDAP_BLOCK)
    block = "\n".join(lines[start : lines.index("{% endif %}", start) + 1])
    env = Environment(
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["dotenv_quote"] = str
    rendered = env.from_string(block).render(OPENCLOUD_LDAP_ENABLED=enabled)
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


class TestBuiltinIdpOnTheDirectory(unittest.TestCase):
    def test_the_builtin_idp_drops_the_enabled_flag_the_schema_lacks(self) -> None:
        self.assertEqual(_ldap_env(True)["IDP_USER_ENABLED_ATTRIBUTE"], "")
        self.assertNotIn("IDP_USER_ENABLED_ATTRIBUTE", _ldap_env(False))


if __name__ == "__main__":
    unittest.main()
