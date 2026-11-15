from __future__ import annotations

import json
import re
import unittest

from jinja2 import (
    ChainableUndefined,
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    select_autoescape,
)

from plugins.filter.url.join import url_join
from plugins.lookup.container_volumes import container_volumes
from utils.cache.applications import get_merged_applications
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "roles/web-app-nextcloud"
APPLICATION_ID = "web-app-nextcloud"
SERVICES = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_META_SERVICES))
ROLE_VARS = load_yaml_any(str(PROJECT_ROOT / ROLE / ROLE_FILE_VARS_MAIN))
COMPOSE_TEMPLATE = f"{ROLE}/{ROLE_FILE_TEMPL_COMPOSE}"
INNER_NGINX_TEMPLATE = f"{ROLE}/templates/docker.conf.j2"
VHOST_TEMPLATE = f"{ROLE}/templates/proxy.conf.j2"
COMPOSE_GUARD = "  {% if NEXTCLOUD_NOTIFY_PUSH_ENABLED | bool %}\n  {% set service_name = NEXTCLOUD_NOTIFY_PUSH_SERVICE %}"

NOTIFY_PUSH_BLOCK = (
    "  notify_push:\n"
    "    <container-base>\n"
    "    <lookup container_image ('web-app-nextcloud', 'nextcloud')>\n"
    "    <lookup compose_only ('container_name', 'nextcloud-notify-push')>\n"
    "    init: true\n"
    '    user: "82:82"\n'
    "    read_only: true\n"
    "    cap_drop:\n"
    "      - ALL\n"
    "    security_opt:\n"
    "      - no-new-privileges:true\n"
    '    entrypoint: ["/usr/local/bin/notify-push.sh", "run"]\n'
    "    environment: # nocheck: compose-environment-from-env-file the shared env.j2 binds NEXTCLOUD_URL to the public URL, which these keys override with the internal proxy URL, and PORT, DATABASE_URL and REDIS_URL there would reach every other service that loads it\n"
    '      PORT: "7867"\n'
    '      NOTIFY_PUSH_APP_DIRECTORY: "/var/www/html/custom_apps/notify_push"\n'
    '      NEXTCLOUD_URL: "{nextcloud_url}"\n'
    '      DATABASE_URL: "mariadb://nextcloud:pa$$word@mariadb:3306/nextcloud"\n'
    '      REDIS_URL: "redis://default:re$$dis@redis:6379"\n'
    "    \n"
    "    volumes:\n"
    "    - data:/var/www/html/:ro\n"
    "    configs:\n"
    "    - source: notify_push_launcher\n"
    "      target: /usr/local/bin/notify-push.sh\n"
    "      mode: 365\n"
    "    <lookup container_healthcheck ('notify_push',)>\n"
    "    expose:\n"
    '      - "7867"\n'
    "    <lookup container_depends_on ('web-app-nextcloud',)>\n"
    "    <lookup container_networks ()>"
)

NEXTCLOUD_URLS = {
    "compose": "http://nextcloud-proxy:80",
    "swarm": "http://nextcloud_proxy:80",
}


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


def _environment(overrides: dict[str, str]) -> Environment:
    env = Environment(
        loader=ChoiceLoader(
            [DictLoader(overrides), FileSystemLoader(str(PROJECT_ROOT))]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=_Marker,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = _bool
    env.filters["path_join"] = lambda parts: "/".join(str(part) for part in parts)
    env.filters["to_json"] = json.dumps
    env.filters["entity_name"] = lambda application_id: application_id.split("-", 2)[-1]
    return env


def _render_compose(template_text: str, *, enabled: bool, mode: str) -> str:
    applications = {APPLICATION_ID: {"services": SERVICES}}
    env = _environment(
        {
            "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
            "roles/sys-svc-container/templates/base.yml.j2": "    <container-base>\n",
            "roles/sys-svc-container/templates/deploy.yml.j2": "    <container-deploy>\n",
            "compose.yml.j2": template_text,
        }
    )
    variables = {
        "application_id": APPLICATION_ID,
        "DEPLOYMENT_MODE": mode,
        "NEXTCLOUD_PROXY_SERVICE": "proxy",
        "NEXTCLOUD_SERVICE": "nextcloud",
        "NEXTCLOUD_CRON_SERVICE": "cron",
        "NEXTCLOUD_TASKPROCESSING_SERVICE": "taskprocessing",
        "NEXTCLOUD_DOCKER_USER_ID": 82,
        "NEXTCLOUD_NOTIFY_PUSH_ENABLED": enabled,
        "NEXTCLOUD_NOTIFY_PUSH_SERVICE": "notify_push",
        "NEXTCLOUD_NOTIFY_PUSH_CONTAINER": "nextcloud-notify-push",
        "NEXTCLOUD_NOTIFY_PUSH_PORT": 7867,
        "NEXTCLOUD_NOTIFY_PUSH_APP_DIRECTORY": "/var/www/html/custom_apps/notify_push",
        "NEXTCLOUD_NOTIFY_PUSH_NEXTCLOUD_URL": NEXTCLOUD_URLS[mode],
        "NEXTCLOUD_NOTIFY_PUSH_LAUNCHER": "/usr/local/bin/notify-push.sh",
    }
    config = {"services.notify_push.enabled": enabled}
    resolved = {
        ("database", "url_full"): "mariadb://nextcloud:pa$word@mariadb:3306/nextcloud",
        ("engine", "url"): "redis://default:re$dis@redis:6379",
    }

    def render_jinja(expression):
        return env.from_string(expression).render(variables)

    def lookup(name, *args, **kwargs):
        if name == "config":
            return config[args[1]]
        if name in ("database", "engine"):
            return resolved[(name, args[-1])]
        if name == "container_volumes":
            block = container_volumes(
                applications, APPLICATION_ID, args[0], render_jinja=render_jinja
            )
            return "\n" + block if block else block
        return f"<lookup {name} {args!r}>"

    env.globals["lookup"] = lookup
    return env.get_template("compose.yml.j2").render(variables)


def _service_block(rendered: str, service: str) -> str | None:
    lines = rendered.splitlines()
    header = f"  {service}:"
    if header not in lines:
        return None
    start = lines.index(header)
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip() and not lines[index].startswith("   ")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).rstrip()


def _render_nginx(template: str, *, enabled: bool) -> str:
    env = _environment(
        {
            "roles/sys-svc-proxy/templates/cdn.conf.j2": "",
            "roles/sys-front-tls/templates/nginx_ssl_header.j2": "",
            "roles/sys-front-inj-all/templates/server.conf.j2": "",
            "roles/sys-svc-proxy/templates/location/html.conf.j2": "",
            "roles/web-app-prometheus/templates/nginx/locations.conf.j2": "",
            "roles/web-svc-seaweedfs/templates/nginx/locations.conf.j2": "",
            "roles/sys-svc-proxy/templates/mcp/vhost.conf.j2": "",
            "roles/sys-svc-proxy/templates/headers/identity_request_strips.conf.j2": "",
            "roles/sys-svc-proxy/templates/headers/forwarded.conf.j2": "",
            "roles/sys-svc-proxy/templates/headers/upstream_strips.conf.j2": "",
        }
    )
    env.globals["lookup"] = lambda name, *args, **kwargs: f"<lookup {name} {args!r}>"
    variables = {
        "application_id": APPLICATION_ID,
        "domain": "next.cloud.example",
        "NEXTCLOUD_PORT": 8001,
        "NEXTCLOUD_NOTIFY_PUSH_ENABLED": enabled,
        "NEXTCLOUD_NOTIFY_PUSH_SERVICE": "notify_push",
        "NEXTCLOUD_NOTIFY_PUSH_PORT": 7867,
        "NEXTCLOUD_NOTIFY_PUSH_LOCATION": ROLE_VARS["NEXTCLOUD_NOTIFY_PUSH_LOCATION"],
    }
    return env.get_template(template).render(variables)


def _location_block(rendered: str, opener: str) -> str | None:
    start = rendered.find(opener)
    if start < 0:
        return None
    end = rendered.find("}", start)
    return rendered[start : end + 1]


def _flags(deployed: list[str], applications: dict | None = None) -> dict:
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    variables = {"group_names": deployed, "applications": applications or {}}
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    _reset_cache_for_tests()
    try:
        merged = get_merged_applications(variables=variables, templar=templar)
    finally:
        _reset_cache_for_tests()
    nextcloud = merged[APPLICATION_ID]
    return {
        "redis": nextcloud["services"]["redis"]["enabled"],
        "talk": nextcloud["services"]["talk"]["enabled"],
        "service": nextcloud["services"]["notify_push"]["enabled"],
        "addon": nextcloud["addons"]["notify_push"]["enabled"],
    }


def _push_route(base_endpoint: str, location: str) -> str:
    websocket = (
        base_endpoint.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    )
    path = "/" + websocket.split("://", 1)[1].split("/", 1)[1]
    return re.sub(f"^{re.escape(location)}(.*)$", r"/\1", path)


class TestNotifyPushComposeService(unittest.TestCase):
    def test_enabled_renders_the_daemon_on_the_nextcloud_image_in_both_modes(self):
        template = read_text(str(PROJECT_ROOT / COMPOSE_TEMPLATE))
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                block = _service_block(
                    _render_compose(template, enabled=True, mode=mode), "notify_push"
                )
                self.assertEqual(
                    block, NOTIFY_PUSH_BLOCK.format(nextcloud_url=NEXTCLOUD_URLS[mode])
                )

    def test_disabled_renders_no_daemon(self):
        template = read_text(str(PROJECT_ROOT / COMPOSE_TEMPLATE))
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                rendered = _render_compose(template, enabled=False, mode=mode)
                self.assertIsNone(_service_block(rendered, "notify_push"))
                self.assertNotIn("notify-push", rendered)

    def test_negative_control_an_unguarded_block_renders_while_disabled(self):
        template = read_text(str(PROJECT_ROOT / COMPOSE_TEMPLATE))
        self.assertIn(COMPOSE_GUARD, template)
        unguarded = template.replace(
            COMPOSE_GUARD,
            "  {% if true %}\n  {% set service_name = NEXTCLOUD_NOTIFY_PUSH_SERVICE %}",
        )
        rendered = _render_compose(unguarded, enabled=False, mode="compose")
        self.assertIsNotNone(_service_block(rendered, "notify_push"))


class TestNotifyPushProxyLocations(unittest.TestCase):
    def test_inner_nginx_strips_the_prefix_and_upgrades_to_the_daemon(self):
        block = _location_block(
            _render_nginx(INNER_NGINX_TEMPLATE, enabled=True), "location ^~ /push/"
        )
        self.assertIsNotNone(block)
        self.assertIn(
            "set $upstream_nextcloud_notify_push http://notify_push:7867;", block
        )
        self.assertIn("rewrite ^/push/(.*)$ /$1 break;", block)
        self.assertIn('proxy_set_header    Connection        "upgrade";', block)

    def test_vhost_routes_the_prefix_through_the_websocket_spot(self):
        block = _location_block(
            _render_nginx(VHOST_TEMPLATE, enabled=True), "location ^~ /push/"
        )
        self.assertIsNotNone(block)
        self.assertIn(
            "<lookup proxy_pass ('web-app-nextcloud', 'nextcloud', 'http')>", block
        )
        self.assertIn("proxy_set_header     Upgrade            $proxy_upgrade;", block)

    def test_disabled_leaves_both_proxies_without_the_prefix(self):
        for template in (INNER_NGINX_TEMPLATE, VHOST_TEMPLATE):
            with self.subTest(template=template):
                self.assertNotIn("/push/", _render_nginx(template, enabled=False))


class TestNotifyPushEndpoint(unittest.TestCase):
    def test_announced_websocket_reaches_the_daemon_route(self):
        location = ROLE_VARS["NEXTCLOUD_NOTIFY_PUSH_LOCATION"]
        base_endpoint = url_join(["https://next.cloud.example/", location])
        self.assertEqual(base_endpoint, "https://next.cloud.example/push")
        self.assertEqual(_push_route(base_endpoint, location), "/ws")

    def test_negative_control_a_trailing_slash_misses_the_daemon_route(self):
        location = ROLE_VARS["NEXTCLOUD_NOTIFY_PUSH_LOCATION"]
        self.assertNotEqual(
            _push_route("https://next.cloud.example/push/", location), "/ws"
        )


class TestNotifyPushFlags(unittest.TestCase):
    def test_follows_redis_with_or_without_talk(self):
        self.assertEqual(
            _flags(["web-app-nextcloud"]),
            {"redis": True, "talk": False, "service": True, "addon": True},
        )
        self.assertEqual(
            _flags(["web-app-nextcloud", "web-svc-coturn"]),
            {"redis": True, "talk": True, "service": True, "addon": True},
        )

    def test_negative_control_no_redis_means_no_daemon(self):
        override = {APPLICATION_ID: {"services": {"redis": {"enabled": False}}}}
        self.assertEqual(
            _flags(["web-app-nextcloud", "web-svc-coturn"], override),
            {"redis": False, "talk": True, "service": False, "addon": False},
        )

    def test_addon_follows_the_daemon(self):
        override = {APPLICATION_ID: {"services": {"notify_push": {"enabled": False}}}}
        self.assertEqual(
            _flags(["web-app-nextcloud", "web-svc-coturn"], override),
            {"redis": True, "talk": True, "service": False, "addon": False},
        )


if __name__ == "__main__":
    unittest.main()
