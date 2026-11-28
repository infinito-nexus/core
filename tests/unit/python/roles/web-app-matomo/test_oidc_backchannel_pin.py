import unittest

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

ROLE = PROJECT_ROOT / "roles/web-app-matomo"
TEMPLATE = f"roles/web-app-matomo/{ROLE_FILE_TEMPL_COMPOSE}"
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))
PINNED = ["auth.example.org:host-gateway"]
RELEASE_DIR = "/opt/matomo"
SERVER_SIDE = {
    "exchange_url": "{{ OIDC.CLIENT.TOKEN_URL }}",
    "user_info_url": "{{ OIDC.CLIENT.USER_INFO_URL }}",
}


def _lookup(name, *terms, **_kwargs):
    if name == "container_extra_hosts":
        return "extra_hosts:\n  - " + PINNED[0]
    if name == "template":
        return "build:\n  context: ."
    if name == "compose_only":
        return f"{terms[0]}: {terms[1]}"
    if name == "container_image":
        return f"image: {terms[1]}"
    return ""


def compose_services() -> dict:
    """
    Returns:
        The ``services`` of the rendered compose file, every lookup stubbed
        and ``container_extra_hosts`` answering with ``PINNED``.
    """
    environment = Environment(
        loader=DictLoader(
            {
                TEMPLATE: read_text(str(PROJECT_ROOT / TEMPLATE)),
                "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
                "roles/sys-svc-container/templates/base.yml.j2": "",
            }
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    environment.globals["lookup"] = _lookup
    rendered = environment.get_template(TEMPLATE).render(
        application_id="web-app-matomo",
        MATOMO_SERVICE="matomo",
        MATOMO_NAME="matomo",
        MATOMO_VERSION="5",
        MATOMO_OIDC_PLUGIN_SOURCE="https://plugins.example.org/oidc.zip",
        MATOMO_OIDC_PLUGIN_ARCHIVE="oidc.zip",
        MATOMO_RELEASE_DIR=RELEASE_DIR,
        DOCKER_BIND_HOST="127.0.0.1",
        MATOMO_BOOTSTRAP_SERVICE="bootstrap",
        MATOMO_BOOTSTRAP_NAME="matomo-bootstrap",
        MATOMO_BOOTSTRAP_ENV_FILE="/opt/compose/matomo/bootstrap.env",
        MATOMO_BOOTSTRAP_PROFILE="bootstrap",
        IS_COMPOSE_MODE=True,
    )
    return load_yaml_str(rendered)["services"]


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
        self.assertEqual(compose_services()["matomo"]["extra_hosts"], PINNED)


if __name__ == "__main__":
    unittest.main()
