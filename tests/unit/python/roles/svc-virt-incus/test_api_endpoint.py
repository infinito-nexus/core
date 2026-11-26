from __future__ import annotations

import unittest

from jinja2 import Environment, nodes

from plugins.lookup.container_extra_hosts import DOCKER_INTERNAL_HOST
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from ._incus import ROLE, VARS, environment, evaluate

NETWORKS = load_yaml_any(
    str(PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"), default_if_missing={}
)
LOOPBACK = evaluate(NETWORKS["NETWORK_LOOPBACK_HOSTS"], NETWORKS)
TASKS = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"), default_if_missing=[])
PLAYWRIGHT_ENV = read_text(str(ROLE / "templates" / "playwright.env.j2"))
SEMAPHORE_COMPOSE = read_text(
    str(PROJECT_ROOT / "roles" / "web-app-semaphore" / ROLE_FILE_TEMPL_COMPOSE)
)
RECORD = "📇 Record the API endpoint and the server certificate in OpenBao"
FQDN = "incus.example.org"
CASES = (
    ("localhost", "[::]:8443", f"https://{DOCKER_INTERNAL_HOST}:8443"),
    ("127.0.0.1", "[::]:8443", f"https://{DOCKER_INTERNAL_HOST}:8443"),
    ("::1", "0.0.0.0:9443", f"https://{DOCKER_INTERNAL_HOST}:9443"),
    (FQDN, "[::]:8443", f"https://{FQDN}:8443"),
)
INVENTORY_NAME_ONLY = "https://{{ inventory_hostname }}:{{ INCUS_API_PORT }}"
ALIAS_ONLY = f"https://{DOCKER_INTERNAL_HOST}:{{{{ INCUS_API_PORT }}}}"


def extra_hosts_calls(source: str) -> list[dict]:
    """Args:
        source: the text of a compose template.

    Returns:
        The keyword arguments of every ``lookup('container_extra_hosts')`` call.
    """
    return [
        {keyword.key: keyword.value.as_const() for keyword in call.kwargs}
        for call in Environment(autoescape=True).parse(source).find_all(nodes.Call)
        if isinstance(call.node, nodes.Name)
        and call.node.name == "lookup"
        and call.args
        and isinstance(call.args[0], nodes.Const)
        and call.args[0].value == "container_extra_hosts"
    ]


def endpoint(expression: str, host: str, listen: str) -> str:
    """Args:
        expression: an endpoint value in the form of ``INCUS_API_ENDPOINT``.
        host: ``inventory_hostname`` of the Incus host.
        listen: ``services.incus.api.listen``.

    Returns:
        The endpoint the expression records for that host.
    """
    port = evaluate(VARS["INCUS_API_PORT"], {"INCUS_API": {"listen": listen}})
    return (
        environment()
        .from_string(expression)
        .render(
            inventory_hostname=host,
            NETWORK_LOOPBACK_HOSTS=LOOPBACK,
            INCUS_API_PORT=port,
        )
    )


def unreachable(expression: str) -> list[str]:
    """Args:
        expression: an endpoint value in the form of ``INCUS_API_ENDPOINT``.

    Returns:
        Every case whose recorded endpoint is not the address the provision
        runner and the Playwright container dial.
    """
    findings = []
    for host, listen, wanted in CASES:
        recorded = endpoint(expression, host, listen)
        if recorded != wanted:
            findings.append(f"{host} {listen}: {recorded}")
    return findings


class TestApiEndpoint(unittest.TestCase):
    def test_a_loopback_host_records_the_container_alias_and_a_name_stays(self):
        self.assertEqual(unreachable(VARS["INCUS_API_ENDPOINT"]), [])

    def test_negative_control_the_inventory_name_alone_is_caught(self):
        self.assertEqual(
            unreachable(INVENTORY_NAME_ONLY),
            [
                "localhost [::]:8443: https://localhost:8443",
                "127.0.0.1 [::]:8443: https://127.0.0.1:8443",
                "::1 0.0.0.0:9443: https://::1:9443",
            ],
        )

    def test_negative_control_the_alias_for_every_host_is_caught(self):
        self.assertEqual(
            unreachable(ALIAS_ONLY),
            [f"{FQDN} [::]:8443: https://{DOCKER_INTERNAL_HOST}:8443"],
        )

    def test_the_loopback_forms_come_from_the_network_spot(self):
        self.assertIn("NETWORK_LOOPBACK_HOSTS", VARS["INCUS_API_ENDPOINT"])
        self.assertEqual(sorted(LOOPBACK), ["127.0.0.1", "::1", "localhost"])

    def test_the_record_and_the_playwright_env_read_the_one_endpoint(self):
        record = next(task for task in TASKS if task.get("name") == RECORD)
        data = record["block"][1]["vars"]["openbao_kv_data"]
        self.assertEqual(data["endpoint"], "{{ INCUS_API_ENDPOINT }}")
        self.assertIn(
            "\nINCUS_API_URL={{ INCUS_API_ENDPOINT | dotenv_quote }}\n", PLAYWRIGHT_ENV
        )

    def test_the_provision_runner_pins_the_alias_to_its_host(self):
        self.assertIn({"host_alias": True}, extra_hosts_calls(SEMAPHORE_COMPOSE))


if __name__ == "__main__":
    unittest.main()
