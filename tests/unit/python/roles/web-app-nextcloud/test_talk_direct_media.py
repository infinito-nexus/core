from __future__ import annotations

import itertools
import unittest
import unittest.mock as mock

from jinja2 import (
    ChainableUndefined,
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
)

import plugins.lookup.container_ports as container_ports_lookup
from plugins.lookup.container_volumes import container_volumes
from utils.cache import _reset_cache_for_tests
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE

ROLE = "roles/web-app-nextcloud"
TEMPLATE = f"{ROLE}/{ROLE_FILE_TEMPL_COMPOSE}"
PUBLIC_IP = "203.0.113.7"
SERVICES = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SERVICES))

TALK_HEAD = (
    "  talk:\n"
    "    <container-base>\n"
    "    <lookup container_healthcheck ('talk',)>\n"
    "    <lookup container_image ('web-app-nextcloud', 'talk')>\n"
    "    <lookup compose_only ('container_name', <NEXTCLOUD_HPB_CONTAINER>)>\n"
    '    command: ["/start.sh", "sh", "<NEXTCLOUD_TALK_BACKENDS_SCRIPT>", "supervisord", "-c", "/supervisord.conf"]\n'
    "    \n"
    "    init: true\n"
)

LEGACY_BRIDGE_ONBOARD = (
    TALK_HEAD
    + """    ports:
      - "203.0.113.7:3480:3480/tcp"
      - "203.0.113.7:3480:3480/udp"
      - "203.0.113.7:50000-59999:50000-59999/udp"
      - "203.0.113.7:50000-59999:50000-59999/tcp"
    expose:
      - "8081"
    <lookup container_networks ()>"""
)

LEGACY_BRIDGE = (
    TALK_HEAD
    + """    expose:
      - "8081"
    <lookup container_networks ()>"""
)

LEGACY_HOST = TALK_HEAD + "    network_mode: host"

DIRECT_MOUNT = (
    "    \n"
    "    configs:\n"
    "    - source: janus_conf\n"
    "      target: /usr/local/etc/janus/janus.jcfg"
)

DIRECT_PORT = '      - "203.0.113.7:61000-61999:61000-61999/udp"'


class _Marker(ChainableUndefined):
    def __str__(self):
        return f"<{self._undefined_name}>"

    __repr__ = __str__


def _bool(value):
    if isinstance(value, bool):
        return value
    if value is None or isinstance(value, ChainableUndefined):
        return False
    return str(value).strip().lower() in {"y", "yes", "true", "on", "1"}


def _render(
    template_text: str, *, onboard: bool, direct: bool, mode: str, network: str
) -> str:
    applications = {"web-app-nextcloud": {"services": SERVICES}}
    env = Environment(
        loader=ChoiceLoader(
            [
                DictLoader(
                    {
                        "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
                        "roles/sys-svc-container/templates/base.yml.j2": "    <container-base>\n",
                        "roles/sys-svc-container/templates/deploy.yml.j2": "    <container-deploy>\n",
                        "compose.yml.j2": template_text,
                    }
                ),
                FileSystemLoader(str(PROJECT_ROOT)),
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=_Marker,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = _bool
    env.filters["path_join"] = lambda parts: "/".join(str(part) for part in parts)
    variables = {
        "application_id": "web-app-nextcloud",
        "NEXTCLOUD_PROXY_SERVICE": "proxy",
        "NEXTCLOUD_SERVICE": "nextcloud",
        "NEXTCLOUD_CRON_SERVICE": "cron",
        "DEPLOYMENT_MODE": mode,
        "NEXTCLOUD_HPB_SIGNALING_ENABLED": True,
        "NEXTCLOUD_HPB_SERVICE": "talk",
        "NEXTCLOUD_HPB_SIGNALING_PORT": 8081,
        "NEXTCLOUD_HPB_NETWORK_MODE": network,
        "NEXTCLOUD_HPB_TURN_ONBOARD_ENABLED": onboard,
        "NEXTCLOUD_HPB_TURN_ONBOARD_PUBLISH_PORTS": True,
        "NEXTCLOUD_HPB_TURN_ONBOARD_BIND_HOST": PUBLIC_IP,
        "NEXTCLOUD_HPB_MEDIA_DIRECT": direct,
        "NEXTCLOUD_HPB_MEDIA_PUBLIC_IP": PUBLIC_IP,
    }

    def render_jinja(expression):
        return env.from_string(expression).render(variables)

    class _Applications:
        def run(self, terms, variables=None):
            return [applications]

    class _Loader:
        def get(self, name, **kwargs):
            return _Applications()

    def lookup(name, *args, **kwargs):
        if name == "config":
            return {"services.talk.direct_media": direct}[args[1]]
        if name == "container_ports":
            with mock.patch.object(container_ports_lookup, "lookup_loader", _Loader()):
                return container_ports_lookup.LookupModule().run(
                    list(args), variables=variables
                )[0]
        if name == "container_volumes":
            block = container_volumes(
                applications, "web-app-nextcloud", args[0], render_jinja=render_jinja
            )
            return "\n" + block if block else block
        return f"<lookup {name} {args!r}>"

    env.globals["lookup"] = lookup
    return env.get_template("compose.yml.j2").render(variables)


def _talk_block(rendered: str) -> str:
    lines = rendered.splitlines()
    start = lines.index("  talk:")
    end = next(
        index
        for index in range(start + 1, len(lines))
        if lines[index].strip() and not lines[index].startswith("   ")
    )
    return "\n".join(lines[start:end]).rstrip()


def _cells(direct: bool):
    for onboard, mode, network in itertools.product(
        (True, False), ("compose", "swarm"), ("bridge", "host")
    ):
        yield {"onboard": onboard, "direct": direct, "mode": mode, "network": network}


def _legacy(cell) -> str:
    if cell["network"] == "host":
        return LEGACY_HOST
    return LEGACY_BRIDGE_ONBOARD if cell["onboard"] else LEGACY_BRIDGE


class TestTalkComposeBlock(unittest.TestCase):
    def test_every_cell_without_direct_media_renders_the_legacy_block(self):
        template = read_text(str(PROJECT_ROOT / TEMPLATE))
        for cell in _cells(direct=False):
            with self.subTest(**cell):
                self.assertEqual(_talk_block(_render(template, **cell)), _legacy(cell))

    def test_direct_media_adds_only_the_janus_mount_and_the_udp_range(self):
        template = read_text(str(PROJECT_ROOT / TEMPLATE))
        for cell in _cells(direct=True):
            if cell["network"] != "bridge":
                continue
            with self.subTest(**cell):
                block = _talk_block(_render(template, **cell))
                legacy = _legacy(cell)
                expected = legacy.replace(
                    "\n    \n    init: true", "\n" + DIRECT_MOUNT + "\n    init: true"
                )
                if cell["onboard"]:
                    expected = expected.replace(
                        "    expose:", DIRECT_PORT + "\n    expose:"
                    )
                else:
                    expected = expected.replace(
                        "    expose:", "    ports:\n" + DIRECT_PORT + "\n    expose:"
                    )
                self.assertEqual(block, expected)

    def test_negative_control_direct_media_does_not_render_the_legacy_block(self):
        template = read_text(str(PROJECT_ROOT / TEMPLATE))
        cell = {
            "onboard": False,
            "direct": True,
            "mode": "compose",
            "network": "bridge",
        }
        rendered = _render(template, **cell)
        self.assertIn("janus_conf", rendered)
        self.assertNotEqual(_talk_block(rendered), _legacy(cell))


def _direct_media(group_names, *, mode="compose", ip4=PUBLIC_IP, applications=None):
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    from utils.cache.applications import get_merged_applications

    variables = {
        "group_names": group_names,
        "applications": applications or {},
        "DEPLOYMENT_MODE": mode,
        "IS_COMPOSE_MODE": mode == "compose",
        "networks": {"internet": {"ip4": ip4, "ip6": "::1"}},
        "ansible_facts": {"all_ipv4_addresses": [PUBLIC_IP, "10.208.0.1"]},
    }
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    _reset_cache_for_tests()
    try:
        merged = get_merged_applications(variables=variables, templar=templar)
    finally:
        _reset_cache_for_tests()
    return merged["web-app-nextcloud"]["services"]["talk"]["direct_media"]


STANDALONE_TURN = ("web-app-nextcloud", "web-svc-coturn")


class TestDirectMediaFlag(unittest.TestCase):
    def test_compose_with_standalone_turn_and_an_owned_address_turns_it_on(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN)), True)

    def test_an_address_the_host_does_not_own_keeps_it_off(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN), ip4="198.51.100.9"), False)

    def test_the_loopback_placeholder_keeps_it_off(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN), ip4="127.0.0.1"), False)

    def test_swarm_keeps_it_off(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN), mode="swarm"), False)

    def test_onboard_turn_keeps_it_off(self):
        forced = {"web-app-nextcloud": {"services": {"talk": {"enabled": True}}}}
        self.assertIs(_direct_media(["web-app-nextcloud"], applications=forced), False)

    def test_host_networking_keeps_it_off(self):
        host = {"web-app-nextcloud": {"services": {"talk": {"network_mode": "host"}}}}
        self.assertIs(_direct_media(list(STANDALONE_TURN), applications=host), False)


if __name__ == "__main__":
    unittest.main()
