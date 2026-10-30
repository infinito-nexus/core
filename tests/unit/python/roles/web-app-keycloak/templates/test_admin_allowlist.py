from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleFilterError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template
from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.networks.proxy import render_proxy_pass
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
TEMPLATE = "roles/web-app-keycloak/templates/nginx/admin_allowlist.conf.j2"
CONFIG_PATH = "services.keycloak.admin.allowed_networks"
LOCAL_HTTP_PORT = 8032
NETWORKS = ("203.0.113.0/24", "2001:db8::/48", "198.51.100.7")
REALM = "example.realm"

STUBBED_FRAGMENTS = {
    "helper_iframes.conf.j2": "HELPER_IFRAMES\n",
    "admin_allowlist.conf.j2": (
        "{% for network in KEYCLOAK_ADMIN_NETWORKS %}allow {{ network }};\n{% endfor %}"
    ),
    "logout_panel.conf.j2": "LOGOUT_PANEL\n",
}

STUBBED_INCLUDES = {
    "roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2": "SSO_GATE\n",
    "roles/sys-svc-proxy/templates/headers/content_security_policy.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/access_control_allow.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/forwarded.conf.j2": "",
    "roles/sys-svc-proxy/templates/headers/untrusted_identity_strips.conf.j2": "",
    "roles/sys-front-inj-all/templates/location.lua.j2": "",
}


def role_filters() -> dict:
    spec = importlib.util.spec_from_file_location(
        "keycloak_admin_networks", ROLE_DIR / "filter_plugins/admin_networks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()


def stub_lookup(networks, deployment_mode: str = "compose"):
    """Return a `lookup` that answers the role's config paths and `proxy_pass`.

    Args:
        networks: the value under `services.keycloak.admin.allowed_networks`.
        deployment_mode: the mode `proxy_pass` renders for.
    """
    config = {
        CONFIG_PATH: networks,
        "services.keycloak.ports.local.http": LOCAL_HTTP_PORT,
    }

    def lookup(kind, *args, **kwargs):
        if kind == "config":
            if args[1] in config:
                return config[args[1]]
            return args[2]
        if kind == "proxy_pass":
            return render_proxy_pass(
                f"127.0.0.1:{kwargs['local_port']}",
                deployment_mode,
                tail=kwargs["tail"],
                location=kwargs["location"],
            )
        raise AssertionError(f"unexpected lookup({kind!r}, ...)")

    return lookup


def admin_networks(networks) -> list[str]:
    """Evaluate the role's `KEYCLOAK_ADMIN_NETWORKS` for a declared value.

    Args:
        networks: the value under `services.keycloak.admin.allowed_networks`.
    """
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters.update(role_filters())
    definition = load_yaml(ROLE_DIR / ROLE_FILE_VARS_MAIN)["KEYCLOAK_ADMIN_NETWORKS"]
    return env.from_string(definition).render(
        application_id="web-app-keycloak", lookup=stub_lookup(networks)
    )


def render(networks, deployment_mode: str = "compose") -> str:
    """Render the allowlist fragment the Keycloak vhost carries.

    Args:
        networks: the value under `services.keycloak.admin.allowed_networks`.
        deployment_mode: the mode `proxy_pass` renders for.
    """
    env = Environment(
        loader=ChoiceLoader(
            [DictLoader(STUBBED_INCLUDES), FileSystemLoader(str(PROJECT_ROOT))]
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
        trim_blocks=True,
    )
    env.filters.update(role_filters())
    env.filters["bool"] = lambda value: (
        value
        if isinstance(value, bool)
        else str(value).strip().lower() in {"true", "1", "yes", "on"}
    )
    env.filters["get_entity_name"] = lambda value: value.rsplit("-", 1)[-1]
    return env.get_template(TEMPLATE).render(
        application_id="web-app-keycloak",
        lookup=stub_lookup(networks, deployment_mode),
        KEYCLOAK_ADMIN_NETWORKS=admin_networks(networks),
        KEYCLOAK_REALM=REALM,
    )


def extra_configuration(networks: list[str], logout_panel_enabled: bool) -> str:
    """Evaluate the vhost extras `tasks/00_core.yml` hands to `sys-stk-full`.

    Ansible's template lookup returns None for a fragment that renders no text,
    and `~` writes it into the vhost as "None"; plain Jinja renders ''.

    Args:
        networks: the resolved `KEYCLOAK_ADMIN_NETWORKS`.
        logout_panel_enabled: the resolved `KEYCLOAK_LOGOUT_PANEL_ENABLED`.
    """
    task = next(
        task
        for task in load_yaml_any(ROLE_DIR / "tasks/00_core.yml")
        if "vars" in task and "webserver_extra_configuration" in task["vars"]
    )
    with tempfile.TemporaryDirectory() as search_path:
        fragments = Path(search_path, "templates", "nginx")
        fragments.mkdir(parents=True)
        for name, text in STUBBED_FRAGMENTS.items():
            (fragments / name).write_text(text, encoding="utf-8")
        templar = Templar(
            loader=DataLoader(),
            variables={
                "ansible_search_path": [search_path],
                "KEYCLOAK_ADMIN_NETWORKS": networks,
                "KEYCLOAK_LOGOUT_PANEL_ENABLED": logout_panel_enabled,
            },
        )
        return templar.template(
            trust_as_template(task["vars"]["webserver_extra_configuration"])
        )


def location_block(rendered: str, path: str) -> tuple[str, list[str]]:
    """Return the matcher and the directives, one per line, of a location.

    Args:
        rendered: the rendered fragment.
        path: the path the location's matcher names, modifier excluded.
    """
    for match in re.finditer(
        r"^location\s+([^{\n]+?)\s*\{([^{}]*)\}", rendered, re.MULTILINE
    ):
        matcher = match.group(1).strip()
        if matcher.split()[-1] == path:
            return matcher, [
                line.strip()
                for line in match.group(2).splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
    raise AssertionError(f"no location for {path} rendered:\n{rendered}")


def covers(matcher: str, path: str) -> bool:
    """Return whether an nginx prefix matcher selects a request path.

    Args:
        matcher: the location matcher, modifier included.
        path: the normalised request path.
    """
    return path.startswith(re.sub(r"^\^~\s*", "", matcher))


class TestShippedValue(unittest.TestCase):
    def test_the_role_ships_no_implicit_allowlist(self):
        services = load_yaml(ROLE_DIR / ROLE_FILE_META_SERVICES)
        self.assertEqual(services["keycloak"]["admin"]["allowed_networks"], [])

    def test_an_empty_list_resolves_to_no_network(self):
        self.assertEqual(admin_networks([]), [])


class TestVhostExtras(unittest.TestCase):
    def test_no_declared_network_adds_no_text(self):
        for panel, expected in (
            (True, "HELPER_IFRAMES\nLOGOUT_PANEL\n"),
            (False, "HELPER_IFRAMES\n"),
        ):
            with self.subTest(logout_panel_enabled=panel):
                self.assertEqual(extra_configuration([], panel), expected)

    def test_declared_networks_sit_between_the_helpers_and_the_panel(self):
        self.assertEqual(
            extra_configuration(["203.0.113.0/24"], True),
            "HELPER_IFRAMES\nallow 203.0.113.0/24;\nLOGOUT_PANEL\n",
        )


class TestRestrictedLocation(unittest.TestCase):
    def test_every_network_is_allowed_before_the_rest_is_denied(self):
        _, directives = location_block(render(list(NETWORKS)), "/admin")
        access = [d for d in directives if d.startswith(("allow ", "deny "))]
        self.assertEqual(
            access,
            [
                "allow 203.0.113.0/24;",
                "allow 2001:db8::/48;",
                "allow 198.51.100.7/32;",
                "deny all;",
            ],
        )

    def test_the_admin_console_and_rest_api_are_covered(self):
        matcher, _ = location_block(render(list(NETWORKS)), "/admin")
        for path in (
            "/admin",
            "/admin/",
            "/admin/master/console/",
            "/admin/realms/infinito/users",
            "/admin/serverinfo",
        ):
            with self.subTest(path=path):
                self.assertTrue(covers(matcher, path))

    def test_the_oidc_endpoints_stay_public(self):
        matcher, _ = location_block(render(list(NETWORKS)), "/admin")
        for path in (
            "/",
            "/realms/infinito/protocol/openid-connect/token",
            "/realms/infinito/.well-known/openid-configuration",
            "/realms/infinito/account/",
            "/resources/abc/admin/keycloak.v2/main.js",
        ):
            with self.subTest(path=path):
                self.assertFalse(covers(matcher, path))

    def test_no_regex_location_can_take_an_admin_path_over(self):
        matcher, _ = location_block(render(list(NETWORKS)), "/admin")
        self.assertTrue(
            matcher.startswith("^~ "),
            f"'{matcher}' lets a regex location win over the allowlist",
        )

    def test_compose_passes_the_request_path_unchanged(self):
        _, directives = location_block(render(list(NETWORKS)), "/admin")
        self.assertIn(
            f"proxy_pass http://127.0.0.1:{LOCAL_HTTP_PORT}/admin;", directives
        )

    def test_swarm_passes_the_raw_request_uri(self):
        _, directives = location_block(render(list(NETWORKS), "swarm"), "/admin")
        self.assertIn("proxy_pass http://$proxy_pass_upstream$request_uri;", directives)

    def test_the_location_strips_forged_identity_headers(self):
        rendered = render(list(NETWORKS))
        self.assertIn('proxy_set_header X-Forwarded-User "";', rendered)
        self.assertNotIn("SSO_GATE", rendered)


class TestRootRedirect(unittest.TestCase):
    def test_the_root_sends_visitors_to_the_realm_account_console(self):
        matcher, directives = location_block(render(list(NETWORKS)), "/")
        self.assertEqual(matcher, "= /")
        self.assertIn(f"return 302 /realms/{REALM}/account/;", directives)

    def test_the_root_is_open_to_every_source(self):
        _, directives = location_block(render(list(NETWORKS)), "/")
        self.assertEqual(
            [d for d in directives if d.startswith(("allow ", "deny "))], []
        )

    def test_the_redirect_target_is_outside_the_restricted_location(self):
        matcher, _ = location_block(render(list(NETWORKS)), "/admin")
        self.assertFalse(covers(matcher, f"/realms/{REALM}/account/"))


class TestDeclaredValues(unittest.TestCase):
    def test_spellings_of_one_network_render_one_allow(self):
        _, directives = location_block(
            render(["2001:db8::1", "2001:0db8::1/128", " 2001:db8::1 "]), "/admin"
        )
        self.assertEqual(
            [d for d in directives if d.startswith("allow ")],
            ["allow 2001:db8::1/128;"],
        )

    def test_malformed_values_fail_the_variable(self):
        for value in (
            "203.0.113.0/24",
            None,
            ["all"],
            ["203.0.113.7/24"],
            ["auth.example.com"],
            [""],
            [42],
            ["fe80::1%eth0"],
            ["fe80::%eth0/64"],
        ):
            with self.subTest(value=value), self.assertRaises(AnsibleFilterError):
                admin_networks(value)


class TestDeployAdminCallsBypassTheVhost(unittest.TestCase):
    LOGIN = re.compile(
        r"config credentials[\s\\]*--server\s+(\"[^\"]*\"|\{\{.*?\}\}|\S+)", re.DOTALL
    )
    INTERNAL_URL_DEFINITION = re.compile(
        r"^\s*KEYCLOAK_SERVER_INTERNAL_URL:\s*\"([^\"]+)\"", re.MULTILINE
    )
    LOOPBACK = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\]):\d+$")

    def _role_sources(self) -> dict[str, str]:
        return {
            path: text
            for path, text in iter_project_files_with_content(
                extensions=(".yml", ".sh", ".j2"), exclude_tests=True
            )
            if "/roles/" in path
        }

    def test_every_kcadm_login_targets_the_container_loopback(self):
        servers = [
            (name, match.group(1).strip('"'))
            for name, text in self._role_sources().items()
            for match in self.LOGIN.finditer(text)
        ]
        self.assertTrue(servers, "no kcadm login found, the scan is vacuous")
        for name, server in servers:
            with self.subTest(source=name, server=server):
                self.assertTrue(
                    server == "{{ KEYCLOAK_SERVER_INTERNAL_URL }}"
                    or self.LOOPBACK.match(server),
                    f"{name} logs kcadm in through {server}, which crosses the "
                    "public vhost and its admin allowlist",
                )

    def test_the_internal_url_is_loopback_wherever_it_is_defined(self):
        definitions = [
            (name, match.group(1))
            for name, text in self._role_sources().items()
            for match in self.INTERNAL_URL_DEFINITION.finditer(text)
        ]
        self.assertTrue(definitions, "KEYCLOAK_SERVER_INTERNAL_URL is defined nowhere")
        for name, url in definitions:
            with self.subTest(source=name):
                self.assertRegex(url, self.LOOPBACK)


if __name__ == "__main__":
    unittest.main()
