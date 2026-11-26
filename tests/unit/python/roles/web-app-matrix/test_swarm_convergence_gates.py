from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

TEMPLATE = "roles/web-app-matrix/templates/flavor/compose/services.yml.j2"
BRIDGES = [
    {"bridge_name": "whatsapp", "appservice_port": 29318},
    {"bridge_name": "telegram", "appservice_port": 29317},
]
CHATGPT = "matrix-chatgpt-bot"


def services(*, chatgpt: bool = False, token: str = "") -> dict:
    """
    Args:
        chatgpt: value of ``services.matrix.plugins.chatgpt``.
        token: value of ``MATRIX_CHATGPT_ACCESS_TOKEN``.

    Returns:
        The services the compose flavor renders for ``BRIDGES``.
    """
    environment = Environment(
        loader=DictLoader(
            {
                TEMPLATE: "services:\n" + read_text(str(PROJECT_ROOT / TEMPLATE)),
                "roles/sys-svc-container/templates/deploy.yml.j2": "",
            }
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    environment.filters["bool"] = bool

    def lookup(name, *terms, **_kwargs):
        if name == "config" and terms[1] == "services.matrix.plugins.chatgpt":
            return chatgpt
        if name in ("config", "mxid"):
            return "x"
        return ""

    environment.globals["lookup"] = lookup
    rendered = environment.get_template(TEMPLATE).render(
        application_id="web-app-matrix",
        DOCKER_BIND_HOST="127.0.0.1",
        MATRIX_BRIDGES=BRIDGES,
        MATRIX_BRIDGE_CONFIG_TARGET="/data/config.yaml",
        MATRIX_CHATGPT_ACCESS_TOKEN=token,
        MATRIX_CHATGPT_BRIDGE_API_KEY="",
        MATRIX_CHATGPT_BRIDGE_ENDPOINT="http://litellm:4000/v1",
        MATRIX_CHATGPT_BRIDGE_MODEL="gpt",
        MATRIX_CHATGPT_ENCRYPTION=False,
        MATRIX_ELEMENT_NAME="matrix-element",
        MATRIX_SERVER_NAME="example.org",
        MATRIX_SYNAPSE_DOMAIN="matrix.example.org",
        MATRIX_SYNAPSE_GID=991,
        MATRIX_SYNAPSE_LOCAL_URL="http://synapse:8008",
        MATRIX_SYNAPSE_NAME="matrix-synapse",
        MATRIX_SYNAPSE_UID=991,
    )
    return load_yaml_str(rendered)["services"]


class TestSwarmConvergenceGates(unittest.TestCase):
    def test_bridge_health_does_not_wait_for_the_homeserver_ping(self) -> None:
        rendered = services()
        for bridge in BRIDGES:
            name = f"mautrix-{bridge['bridge_name']}"
            with self.subTest(bridge=name):
                self.assertEqual(
                    urlsplit(rendered[name]["healthcheck"]["test"][-1]).path,
                    "/_matrix/mau/live",
                    "a /ready probe waits for Synapse to reach the bridge, which "
                    "swarm only allows once the task is healthy",
                )

    def test_chatgpt_bot_waits_for_the_token_provisioning_issues(self) -> None:
        for chatgpt, token, scheduled in (
            (True, "", False),
            (True, "syt_token", True),
            (False, "syt_token", False),
        ):
            with self.subTest(chatgpt=chatgpt, token=token):
                self.assertIs(
                    CHATGPT in services(chatgpt=chatgpt, token=token),
                    scheduled,
                    "the bot account and its token only exist after "
                    "stack_host_provisioning, so an earlier bot task fails its "
                    "login until swarm's converge wait calls it stuck",
                )


if __name__ == "__main__":
    unittest.main()
