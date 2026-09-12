import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

SSO_PROXY_TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks/sso_proxy.yml"
CONTAINER_TEMPLATE = (
    PROJECT_ROOT / "roles/web-app-keycloak/templates/sso_proxy/container.yml.j2"
)
_RENDERED_CFG = re.compile(r"src:\s*\"\{\{\s*lookup\('path_absolute',\s*'([^']+)'\)")
_HASHED_CFG = re.compile(
    r"^\s+labels:\n\s+[\w.-]+:\s*\"\{\{\s*lookup\('template',\s*"
    r"lookup\('path_absolute',\s*'([^']+)'\).*\|\s*hash\('sha256'\)\s*\}\}\"",
    re.MULTILINE,
)


class TestSsoProxyRestartsOnConfigChange(unittest.TestCase):
    def test_the_sidecar_labels_a_hash_of_the_config_it_mounts(self) -> None:
        rendered = _RENDERED_CFG.search(read_text(str(SSO_PROXY_TASKS)))
        hashed = _HASHED_CFG.search(read_text(str(CONTAINER_TEMPLATE)))
        self.assertIsNotNone(
            rendered, f"{SSO_PROXY_TASKS} no longer renders a path_absolute src"
        )
        self.assertIsNotNone(
            hashed,
            "the sso-proxy service must carry a label hashing its rendered "
            "config: the config is a bind mount oauth2-proxy reads at start, "
            "and docker stack deploy only restarts a service whose spec "
            "changed, so a rotated redis password or client secret leaves "
            "the running sidecar on the old one (WRONGPASS, HTTP 500)",
        )
        self.assertEqual(
            rendered.group(1),
            hashed.group(1),
            "the label must hash the same template sso_proxy.yml renders",
        )


if __name__ == "__main__":
    unittest.main()
