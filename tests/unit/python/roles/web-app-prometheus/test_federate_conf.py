from __future__ import annotations

import re
import unittest
from urllib.parse import parse_qs

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.platform.monitoring import FilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.networks.proxy import render_proxy_pass
from utils.platform_monitoring import FEDERATE_MATCHES, FEDERATED

TEMPLATE = "roles/web-app-prometheus/templates/nginx/federate.conf.j2"
LOCATIONS = PROJECT_ROOT / "roles/web-app-prometheus/templates/nginx/locations.conf.j2"
CONF_BASE = "/etc/nginx/conf.d/"
GROUP = "svc-net-platform-monitoring"
HOST = "customer"
AUTHORITY = {"compose": "127.0.0.1:8066", "swarm": "prometheus:9090"}
PROMETHEUS_ADDRESS = "198.51.100.7"
WORKSPACE_ENV = {
    "WORKSPACE": "0a1b2c3d-0000-4000-8000-00000000000a",
    "PLATFORM_PROMETHEUS_ADDRESS": PROMETHEUS_ADDRESS,
}


def lookup_for(mode, environment):
    """Args:
    mode: ``compose`` or ``swarm``, the deployment mode ``proxy_pass`` renders.
    environment: the deploy environment ``lookup('env')`` reads.

    Returns:
        A ``lookup`` stub whose ``proxy_pass`` is the real renderer.
    """

    def lookup(name, *terms, **kwargs):
        if name == "env":
            assert terms in (("WORKSPACE",), ("PLATFORM_PROMETHEUS_ADDRESS",))
            return environment.get(terms[0], "")
        if name == "nginx":
            assert terms == ("directories.configuration.base",)
            return CONF_BASE
        if name == "config":
            assert terms == (
                "web-app-prometheus",
                "services.prometheus.ports.local.http",
            )
            return 8066
        if name == "proxy_pass":
            assert terms[:2] == ("web-app-prometheus", "prometheus")
            return render_proxy_pass(AUTHORITY[mode], mode, tail=kwargs["tail"])
        raise AssertionError(name)

    return lookup


def render(mode="compose", group_names=(GROUP,), environment=None, **host):
    """Args:
    mode: the deployment mode.
    group_names: the groups of the rendered host.
    environment: the deploy environment, None for a deploy outside a
        workspace.
    host: the host variables, ``platform_monitoring`` among them.

    Returns:
        The rendered federation locations.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters.update(FilterModule().filters())
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )
    env.globals["lookup"] = lookup_for(mode, environment or {})
    return env.get_template(TEMPLATE).render(
        group_names=list(group_names),
        inventory_hostname=HOST,
        hostvars={HOST: host},
    )


def selectors(rendered):
    """Args:
    rendered: the output of ``render``.

    Returns:
        The ``match[]`` values the ``proxy_pass`` URI pins.
    """
    upstream = re.search(
        r"proxy_pass http://\S+?/federate\?(?P<args>[^;\s]+);", rendered
    )
    assert upstream is not None, rendered
    return parse_qs(upstream["args"], strict_parsing=True)["match[]"]


class FederateConfTests(unittest.TestCase):
    def test_an_absent_share_answers_every_federated_kind(self):
        for mode in AUTHORITY:
            with self.subTest(mode):
                self.assertEqual(
                    selectors(render(mode)),
                    [
                        selector
                        for kind in FEDERATED
                        for selector in FEDERATE_MATCHES[kind]
                    ],
                )

    def test_each_kind_switched_off_drops_its_series_only(self):
        for kind in FEDERATED:
            with self.subTest(kind):
                pinned = selectors(render(platform_monitoring={kind: False}))
                for other in FEDERATED:
                    for selector in FEDERATE_MATCHES[other]:
                        if other == kind:
                            self.assertNotIn(selector, pinned)
                        else:
                            self.assertIn(selector, pinned)

    def test_all_three_off_serves_no_federate(self):
        rendered = render(platform_monitoring=dict.fromkeys(FEDERATED, False))
        self.assertIn("return 404;", rendered)
        self.assertNotIn("proxy_pass", rendered)

    def test_a_host_outside_the_share_keeps_the_old_federate(self):
        self.assertEqual(render(group_names=("web-app-prometheus",)).strip(), "")

    def test_the_callers_query_is_dropped_in_both_modes(self):
        for mode in AUTHORITY:
            with self.subTest(mode):
                rendered = render(mode)
                self.assertNotIn("rewrite", rendered)
                self.assertNotIn("$request_uri", rendered)
                self.assertNotIn("$args;", rendered)
                self.assertLess(
                    rendered.index('set $args "";'), rendered.index("proxy_pass")
                )
                self.assertIn('proxy_set_header Authorization "";', rendered)

    def test_swarm_sets_the_upstream_before_it_proxies(self):
        rendered = render("swarm")
        self.assertIn(
            f'set $proxy_pass_upstream "{AUTHORITY["swarm"]}";\n'
            "    proxy_pass http://$proxy_pass_upstream/federate?",
            rendered,
        )

    def test_compose_proxies_the_pinned_uri_literally(self):
        self.assertIn(
            f"proxy_pass http://{AUTHORITY['compose']}/federate?match%5B%5D=", render()
        )

    def test_the_bearer_is_checked_against_the_digest_file(self):
        rendered = render()
        self.assertIn(f'io.open("{CONF_BASE}federate.sha256", "r")', rendered)
        self.assertIn(
            "if not handle then\n        return ngx.exit(ngx.HTTP_UNAUTHORIZED)",
            rendered,
        )
        self.assertIn('require("resty.sha256")', rendered)
        self.assertIn("for line in handle:lines() do", rendered)
        self.assertIn('line:match("^%S+ (%x+)$")', rendered)
        self.assertNotIn('handle:read("*l")', rendered)
        self.assertIn("limit_except GET", rendered)
        self.assertLess(
            rendered.index("access_by_lua_block"), rendered.index("proxy_pass")
        )

    def test_a_workspace_serves_only_the_platform_prometheus(self):
        rendered = render(environment=WORKSPACE_ENV)
        allowed = re.findall(r"^\s*allow (\S+);$", rendered, re.MULTILINE)
        self.assertEqual(allowed, [PROMETHEUS_ADDRESS])
        deny = rendered.index("deny all;")
        self.assertLess(rendered.rindex("allow"), deny)
        self.assertLess(deny, rendered.index("limit_except"))
        self.assertLess(deny, rendered.index("access_by_lua_block"))

    def test_a_foreign_source_is_never_allowed(self):
        rendered = render(environment=WORKSPACE_ENV)
        self.assertNotIn("allow all", rendered)
        self.assertNotIn("allow 192.0.2.66", rendered)
        self.assertNotIn("allow 127.0.0.1", rendered)
        self.assertNotIn("allow ::1", rendered)

    def test_a_workspace_without_a_platform_address_fails_the_render(self):
        for address in ("", "prometheus.example.org", "fe80::1%eth0", "192.0.2.7\n"):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(Exception, "PLATFORM_PROMETHEUS_ADDRESS"),
            ):
                render(
                    environment={
                        **WORKSPACE_ENV,
                        "PLATFORM_PROMETHEUS_ADDRESS": address,
                    }
                )

    def test_outside_a_workspace_the_bearer_alone_guards_it(self):
        rendered = render()
        self.assertNotRegex(rendered, r"(?m)^\s*allow ")
        self.assertLess(rendered.index("limit_except"), rendered.index("deny all;"))

    def test_a_broken_share_fails_the_render(self):
        with self.assertRaisesRegex(Exception, "platform_monitoring.logs"):
            render(platform_monitoring={"logs": True})

    def test_the_prometheus_vhost_alone_includes_it(self):
        text = read_text(str(LOCATIONS))
        block = text[text.index("{% if application_id == 'web-app-prometheus' %}") :]
        block = block[: block.index("{% endif %}")]
        self.assertIn(TEMPLATE, block)


if __name__ == "__main__":
    unittest.main()
