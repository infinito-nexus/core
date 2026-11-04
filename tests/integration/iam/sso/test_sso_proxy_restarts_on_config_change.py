import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SSO_PROXY_TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks/sso_proxy.yml"
CONTAINER_TEMPLATE = (
    PROJECT_ROOT / "roles/web-app-keycloak/templates/sso_proxy/container.yml.j2"
)
_RENDERED_CFG = re.compile(r"src:\s*\"\{\{\s*lookup\('path_absolute',\s*'([^']+)'\)")
_HASH_LABEL = re.compile(
    r"^\s+labels:\n\s+[\w.-]+:\s*\"\{\{(?P<expr>.*\|\s*hash\('sha256'\))\s*\}\}\"",
    re.MULTILINE,
)
_HASHED_TEMPLATE = re.compile(
    r"lookup\('template',\s*lookup\('path_absolute',\s*'([^']+)'\)"
)


class TestSsoProxyRestartsOnConfigChange(unittest.TestCase):
    def test_the_sidecar_labels_a_hash_of_the_config_it_mounts(self) -> None:
        rendered = _RENDERED_CFG.findall(read_text(str(SSO_PROXY_TASKS)))
        label = _HASH_LABEL.search(read_text(str(CONTAINER_TEMPLATE)))
        self.assertTrue(
            rendered, f"{SSO_PROXY_TASKS} no longer renders a path_absolute src"
        )
        self.assertIsNotNone(
            label,
            "the sso-proxy service must carry a label hashing its rendered "
            "config: the config is a bind mount oauth2-proxy reads at start, "
            "and docker stack deploy only restarts a service whose spec "
            "changed, so a rotated redis password or client secret leaves "
            "the running sidecar on the old one (WRONGPASS, HTTP 500)",
        )
        self.assertEqual(
            sorted(set(_HASHED_TEMPLATE.findall(label.group("expr")))),
            sorted(set(rendered)),
            "the label must hash every template sso_proxy.yml renders",
        )


if __name__ == "__main__":
    unittest.main()
