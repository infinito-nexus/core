from __future__ import annotations

import json
import re
import shlex
import unittest

from jinja2 import (
    ChainableUndefined,
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from plugins.filter.url.join import url_join
from plugins.lookup.container_volumes import container_volumes
from utils.cache.applications import get_merged_applications
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import network_of
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)
from utils.tests.caches import fresh_caches

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

TASKS_FILE = PROJECT_ROOT / ROLE / "tasks/addons/notify_push.yml"
ONION_DOMAIN = "next.cloud." + "a" * 56 + ".onion"
CLEARNET_DOMAIN = "next.cloud.infinito.example"
TOR_SOCKS_PROXY = "socks5h://host.docker.internal:9050"
DOCKER_EXEC = ["container", "exec", "-u", "www-data", "4f1c2b"]
OCC = "/var/www/html/occ"
PRE_FIX_SELF_TEST = (
    "{{ NEXTCLOUD_DOCKER_EXEC_OCC }} notify_push:setup "
    "{{ NEXTCLOUD_NOTIFY_PUSH_URL | quote }}"
)


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
    with fresh_caches(files_changed=False):
        merged = get_merged_applications(variables=variables, templar=templar)
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


def _render_role_expression(expression: str, scope: dict) -> str:
    """
    Args:
        expression: a Jinja expression of the role's tasks or ``vars/main.yml``.
        scope: the values that stand in for lookups and facts.

    Returns:
        The expression rendered strictly, with every role var it names that
        ``scope`` does not hold rendered from ``vars/main.yml`` first.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["network_of"] = network_of
    env.filters["quote"] = shlex.quote
    names = set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", expression))
    resolved = {
        name: _render_role_expression(ROLE_VARS[name], scope)
        for name in names & ROLE_VARS.keys() - scope.keys()
    }
    return env.from_string(expression).render({**scope, **resolved})


def _self_test_command() -> str:
    tasks = load_yaml_any(str(TASKS_FILE))
    [task] = [entry for entry in tasks if "notify_push:setup" in str(entry)]
    return task["ansible.builtin.command"]["cmd"]


def _direct_argv(domain: str) -> list[str]:
    """
    Args:
        domain: the Nextcloud domain of the deployment.

    Returns:
        The self-test argv that reaches the push URL without any proxy.
    """
    return [*DOCKER_EXEC, OCC, "notify_push:setup", f"http://{domain}/push"]


def _self_test_argv(domain: str, command: str) -> list[str]:
    """
    Args:
        domain: the Nextcloud domain of the deployment.
        command: the ``cmd`` of the self-test task to render.

    Returns:
        The argv the command module runs for the self-test.
    """
    scope = {
        "NEXTCLOUD_DOMAIN": domain,
        "NEXTCLOUD_TOR_SOCKS_PROXY": TOR_SOCKS_PROXY,
        "NEXTCLOUD_DOCKER_EXEC": shlex.join(DOCKER_EXEC),
        "NEXTCLOUD_INTERNAL_OCC_COMMAND": OCC,
        "NEXTCLOUD_NOTIFY_PUSH_URL": f"http://{domain}/push",
    }
    return shlex.split(_render_role_expression(command, scope))


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


class TestNotifyPushWebsocketTaskWiring(unittest.TestCase):
    def test_patch_then_fail_closed_probe_follow_the_setup(self):
        tasks = load_yaml_any(str(TASKS_FILE))
        programs = {
            re.search(
                r"'(php/addons/notify_push/[a-z_/]+\.php)'",
                task["ansible.builtin.command"]["stdin"],
            ).group(1): index
            for index, task in enumerate(tasks)
            if "stdin" in task.get("ansible.builtin.command", {})
        }
        setup = next(
            i for i, task in enumerate(tasks) if "notify_push:setup" in str(task)
        )
        patch = programs["php/addons/notify_push/websocket/patch.php"]
        probe = programs["php/addons/notify_push/websocket/probe.php"]
        self.assertLess(setup, patch)
        self.assertLess(patch, probe)
        for program in programs:
            with self.subTest(program=program):
                self.assertTrue((PROJECT_ROOT / ROLE / "files" / program).is_file())
        probe_task = tasks[probe]
        self.assertEqual(
            probe_task["loop"], "{{ lookup('network_siblings', NEXTCLOUD_DOMAIN) }}"
        )
        self.assertIn(
            "lookup('tls', nextcloud_notify_push_sibling, 'url.origin')",
            probe_task["ansible.builtin.command"]["cmd"],
        )
        for key in ("failed_when", "ignore_errors", "until"):
            with self.subTest(key=key):
                self.assertNotIn(key, probe_task)


class TestNotifyPushSelfTestTorProxy(unittest.TestCase):
    def test_an_onion_self_test_runs_through_the_tor_socks_proxy(self):
        self.assertEqual(
            _self_test_argv(ONION_DOMAIN, _self_test_command()),
            [
                *DOCKER_EXEC,
                "env",
                f"HTTP_PROXY={TOR_SOCKS_PROXY}",
                f"HTTPS_PROXY={TOR_SOCKS_PROXY}",
                OCC,
                "notify_push:setup",
                f"http://{ONION_DOMAIN}/push",
            ],
            "libcurl refuses an .onion host under RFC 7686 unless a socks5h "
            "proxy resolves it",
        )

    def test_a_clearnet_self_test_stays_direct(self):
        self.assertEqual(
            _self_test_argv(CLEARNET_DOMAIN, _self_test_command()),
            _direct_argv(CLEARNET_DOMAIN),
            "a broken clearnet push route must keep failing the self-test",
        )

    def test_negative_control_the_pre_fix_self_test_sends_the_onion_unproxied(self):
        self.assertEqual(
            _self_test_argv(ONION_DOMAIN, PRE_FIX_SELF_TEST),
            _direct_argv(ONION_DOMAIN),
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
