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
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "roles/web-app-nextcloud"
TEMPLATE = f"{ROLE}/{ROLE_FILE_TEMPL_COMPOSE}"
PUBLIC_IP = "203.0.113.7"
SERVICES = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SERVICES))
TALK_SERVICES = ("talk", "talk_signaling", "talk_nats", "talk_recording")

JANUS_HEAD = """  talk:
    <container-base>
    build:
      context: <NEXTCLOUD_HPB_JANUS_BUILD_DIRECTORY>
      dockerfile: Dockerfile
      args:
        JANUS_BASE_IMAGE: "<NEXTCLOUD_HPB_JANUS_BASE_IMAGE>"
        JANUS_BASE_VERSION: "<NEXTCLOUD_HPB_JANUS_BASE_VERSION>"
        JANUS_REPOSITORY: "<NEXTCLOUD_HPB_JANUS_REPOSITORY>"
        JANUS_REF: "<NEXTCLOUD_HPB_JANUS_REF>"
    <lookup compose_only ('pull_policy', 'never')>
    <lookup container_image ('web-app-nextcloud', 'talk') {'version': <NEXTCLOUD_HPB_JANUS_TAG>}>
    <lookup compose_only ('container_name', <NEXTCLOUD_HPB_CONTAINER>)>
    command: ["--config=<NEXTCLOUD_HPB_JANUS_CONFIG_TARGET>"]
    init: true
    <lookup container_healthcheck ('talk',)>
    \n    configs:
    - source: janus_conf
      target: /usr/local/etc/janus/janus.jcfg
      mode: 292"""

JANUS_HOST = JANUS_HEAD + "\n    network_mode: host"

JANUS_BRIDGE = (
    JANUS_HEAD
    + """
    expose:
      - "<NEXTCLOUD_HPB_JANUS_PORT>"
    <lookup container_networks () {'own_network_only': True, 'provider_self_alias': False}>"""
)

DIRECT_PORT = (
    '    ports:\n      - "203.0.113.7:61000-61999:61000-61999/udp"\n    expose:'
)

SIGNALING = """  talk_signaling:
    <container-base>
    <lookup container_image ('web-app-nextcloud', 'talk_signaling')>
    <lookup compose_only ('container_name', <NEXTCLOUD_HPB_SIGNALING_CONTAINER>)>
    user: "<NEXTCLOUD_HPB_SIGNALING_USER_ID>:<NEXTCLOUD_HPB_SIGNALING_USER_ID>"
    command: ["<NEXTCLOUD_HPB_SIGNALING_BINARY>", "-config", "<NEXTCLOUD_HPB_SIGNALING_CONFIG_TARGET>"]
    <lookup container_healthcheck ('talk_signaling',)>
    \n    secrets:
    - source: talk_signaling_conf
      target: /config/server.conf
      mode: 292
    expose:
      - "<NEXTCLOUD_HPB_SIGNALING_PORT>"
    <lookup container_extra_hosts () {'host_alias': {host_alias}}>
    <lookup container_networks () {'provider_self_alias': False}>"""

NATS = """  talk_nats:
    <container-base>
    <lookup container_image ('web-app-nextcloud', 'talk_nats')>
    <lookup compose_only ('container_name', <NEXTCLOUD_HPB_NATS_CONTAINER>)>
    user: "<NEXTCLOUD_HPB_NATS_USER_ID>:<NEXTCLOUD_HPB_NATS_USER_ID>"
    command: ["nats-server", "--addr", "0.0.0.0", "--port", "<NEXTCLOUD_HPB_NATS_PORT>", "--http_port", "<NEXTCLOUD_HPB_NATS_MONITOR_PORT>"]
    <lookup container_healthcheck ('talk_nats',)>
    expose:
      - "<NEXTCLOUD_HPB_NATS_PORT>"
    <lookup container_networks () {'own_network_only': True, 'provider_self_alias': False}>"""

RECORDING = """  talk_recording:
    <container-base>
    build:
      context: <NEXTCLOUD_RECORDING_BUILD_DIRECTORY>
      dockerfile: Dockerfile
      args:
        RECORDING_BASE_IMAGE: "<NEXTCLOUD_RECORDING_BASE_IMAGE>"
        RECORDING_BASE_VERSION: "<NEXTCLOUD_RECORDING_BASE_VERSION>"
        RECORDING_REPOSITORY: "<NEXTCLOUD_RECORDING_REPOSITORY>"
        RECORDING_REF: "<NEXTCLOUD_RECORDING_REF>"
        RECORDING_USER_ID: "<NEXTCLOUD_RECORDING_USER_ID>"
        RECORDING_DIRECTORY: "<NEXTCLOUD_RECORDING_DIRECTORY>"
        RECORDING_CONFIG_DIRECTORY: "<dirname <NEXTCLOUD_RECORDING_CONFIG_TARGET>>"
        RECORDING_CA_CERT: "<NEXTCLOUD_RECORDING_CA_CERT>"
    <lookup compose_only ('pull_policy', 'never')>
    <lookup container_image ('web-app-nextcloud', 'talk_recording') {'version': <NEXTCLOUD_RECORDING_TAG>}>
    <lookup compose_only ('container_name', <NEXTCLOUD_RECORDING_CONTAINER>)>
    command: ["--config", "<NEXTCLOUD_RECORDING_CONFIG_TARGET>"]
    environment:
      TZ: "<HOST_TIMEZONE>"
    <lookup container_healthcheck ('talk_recording',)>
    expose:
      - "<NEXTCLOUD_RECORDING_PORT>"
    <lookup container_networks () {'provider_self_alias': False}>
    \n    volumes:
    - talk_recording_tmp:/tmp
    secrets:
    - source: talk_recording_conf
      target: /conf/recording.conf
      mode: 292"""


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


def _render(template_text: str, *, direct: bool, mode: str, network: str) -> str:
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
    env.filters["dirname"] = lambda value: f"<dirname {value}>"
    variables = {
        "application_id": "web-app-nextcloud",
        "NEXTCLOUD_PROXY_SERVICE": "proxy",
        "NEXTCLOUD_SERVICE": "nextcloud",
        "NEXTCLOUD_CRON_SERVICE": "cron",
        "NEXTCLOUD_TASKPROCESSING_SERVICE": "taskprocessing",
        "DEPLOYMENT_MODE": mode,
        "NEXTCLOUD_HPB_SIGNALING_ENABLED": True,
        "NEXTCLOUD_HPB_SERVICE": "talk",
        "NEXTCLOUD_HPB_SIGNALING_SERVICE": "talk_signaling",
        "NEXTCLOUD_HPB_NATS_SERVICE": "talk_nats",
        "NEXTCLOUD_RECORDING_SERVICE": "talk_recording",
        "NEXTCLOUD_RECORDING_ENABLED": True,
        "NEXTCLOUD_HPB_NETWORK_MODE": network,
        "NEXTCLOUD_HPB_JANUS_HOST_NETWORK": network == "host",
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
            return {
                "services.talk.direct_media": direct,
                "services.talk.enabled": True,
            }[args[1]]
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
        suffix = f" {dict(sorted(kwargs.items()))!r}" if kwargs else ""
        return f"<lookup {name} {args!r}{suffix}>"

    env.globals["lookup"] = lookup
    return env.get_template("compose.yml.j2").render(variables)


def _block(rendered: str, service: str) -> str:
    lines = rendered.splitlines()
    start = lines.index(f"  {service}:")
    end = next(
        index
        for index in range(start + 1, len(lines))
        if lines[index].strip() and not lines[index].startswith("   ")
    )
    return "\n".join(lines[start:end]).rstrip()


def _cells():
    for direct, mode, network in itertools.product(
        (True, False), ("compose", "swarm"), ("bridge", "host")
    ):
        yield {"direct": direct, "mode": mode, "network": network}


def _expected_janus(cell) -> str:
    if cell["mode"] == "compose" and cell["network"] == "host":
        return JANUS_HOST
    if cell["direct"]:
        return JANUS_BRIDGE.replace("    expose:", DIRECT_PORT)
    return JANUS_BRIDGE


def _template() -> str:
    return read_text(str(PROJECT_ROOT / TEMPLATE))


class TestTalkComposeBlocks(unittest.TestCase):
    def test_janus_block_follows_network_mode_and_direct_media(self):
        for cell in _cells():
            with self.subTest(**cell):
                self.assertEqual(
                    _block(_render(_template(), **cell), "talk"), _expected_janus(cell)
                )

    def test_signaling_block_is_the_same_in_every_cell(self):
        for cell in _cells():
            with self.subTest(**cell):
                expected = SIGNALING.replace(
                    "{host_alias}", str(cell["network"] == "host")
                )
                self.assertEqual(
                    _block(_render(_template(), **cell), "talk_signaling"), expected
                )

    def test_nats_and_recording_blocks_are_the_same_in_every_cell(self):
        for cell in _cells():
            with self.subTest(**cell):
                rendered = _render(_template(), **cell)
                self.assertEqual(_block(rendered, "talk_nats"), NATS)
                self.assertEqual(_block(rendered, "talk_recording"), RECORDING)

    def test_no_talk_service_passes_a_secret_through_compose(self):
        for cell in _cells():
            rendered = _render(_template(), **cell)
            for service in TALK_SERVICES:
                with self.subTest(service=service, **cell):
                    self.assertNotIn("SECRET", _block(rendered, service))

    def test_negative_control_an_ungated_host_network_reaches_swarm(self):
        template = _template().replace(
            "{% if DEPLOYMENT_MODE == 'compose' and NEXTCLOUD_HPB_JANUS_HOST_NETWORK | bool %}",
            "{% if NEXTCLOUD_HPB_JANUS_HOST_NETWORK | bool %}",
        )
        cell = {"direct": False, "mode": "swarm", "network": "host"}
        self.assertNotEqual(template, _template())
        block = _block(_render(template, **cell), "talk")
        self.assertIn("network_mode: host", block)
        self.assertNotEqual(block, _expected_janus(cell))

    def test_negative_control_a_secret_in_the_environment_is_caught(self):
        template = _template().replace(
            '      TZ: "{{ HOST_TIMEZONE }}"',
            '      TZ: "{{ HOST_TIMEZONE }}"\n'
            '      RECORDING_SECRET: "{{ NEXTCLOUD_RECORDING_SECRET }}"',
        )
        self.assertNotEqual(template, _template())
        block = _block(
            _render(template, direct=False, mode="compose", network="bridge"),
            "talk_recording",
        )
        self.assertIn("SECRET", block)


ROLE_VARS = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
DIRECT_MEDIA_CHAIN = (
    "NEXTCLOUD_HPB_PLUGIN_ENABLED",
    "NEXTCLOUD_HPB_SIGNALING_ENABLED",
    "NEXTCLOUD_HPB_TURN_STANDALONE_ENABLED",
    "NEXTCLOUD_HPB_HOST_ADDRESSES",
)


def _direct_media(
    group_names, *, mode="compose", ip4=PUBLIC_IP, applications=None, facts=True
):
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar, trust_as_template

    variables = {
        "group_names": group_names,
        "applications": applications or {},
        "application_id": "web-app-nextcloud",
        "NEXTCLOUD_HPB_SERVICE": "talk",
        "DEPLOYMENT_MODE": mode,
        "networks": {"internet": {"ip4": ip4, "ip6": "::1"}},
        **{name: trust_as_template(ROLE_VARS[name]) for name in DIRECT_MEDIA_CHAIN},
    }
    if facts:
        variables["ansible_facts"] = {"all_ipv4_addresses": [PUBLIC_IP, "10.208.0.1"]}
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    _reset_cache_for_tests()
    try:
        return templar.template(
            trust_as_template(ROLE_VARS["NEXTCLOUD_HPB_MEDIA_DIRECT"])
        )
    finally:
        _reset_cache_for_tests()


STANDALONE_TURN = ("web-app-nextcloud", "web-svc-coturn")


def _talk(**talk):
    return {"web-app-nextcloud": {"services": {"talk": talk}}}


OPTED_IN = _talk(direct_media=True)


class TestDirectMediaFlag(unittest.TestCase):
    def test_by_default_every_stream_goes_through_turn(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN)), False)

    def test_opting_in_with_standalone_turn_and_an_owned_address_turns_it_on(self):
        self.assertIs(_direct_media(list(STANDALONE_TURN), applications=OPTED_IN), True)

    def test_host_networking_keeps_it_on(self):
        host = _talk(direct_media=True, network_mode="host")
        self.assertIs(_direct_media(list(STANDALONE_TURN), applications=host), True)

    def test_an_address_the_host_does_not_own_keeps_it_off(self):
        self.assertIs(
            _direct_media(
                list(STANDALONE_TURN), ip4="198.51.100.9", applications=OPTED_IN
            ),
            False,
        )

    def test_the_loopback_placeholder_keeps_it_off(self):
        self.assertIs(
            _direct_media(list(STANDALONE_TURN), ip4="127.0.0.1", applications=OPTED_IN),
            False,
        )

    def test_swarm_keeps_it_off(self):
        self.assertIs(
            _direct_media(list(STANDALONE_TURN), mode="swarm", applications=OPTED_IN),
            False,
        )

    def test_talk_without_coturn_keeps_it_off(self):
        forced = _talk(enabled=True, direct_media=True)
        self.assertIs(_direct_media(["web-app-nextcloud"], applications=forced), False)

    def test_missing_host_facts_render_false_instead_of_a_raw_expression(self):
        self.assertIs(
            _direct_media(list(STANDALONE_TURN), facts=False, applications=OPTED_IN),
            False,
        )


if __name__ == "__main__":
    unittest.main()
