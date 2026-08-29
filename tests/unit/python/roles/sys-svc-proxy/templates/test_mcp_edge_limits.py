"""The edge limits a public MCP surface is served behind.

Every role declares seven `mcp.limits`, and the adapter enforces five of them
on its own request path. Two only ever bite at the reverse proxy:
`concurrent_requests`, which no adapter sees until a connection already
occupies a thread, and `stream_seconds`, which bounds a held stream the
adapter never holds. These templates are where the declaration becomes an
nginx directive, so the values are pinned here rather than merely rendered.
"""

from __future__ import annotations

import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "roles/sys-svc-proxy/templates/mcp"

PUBLIC_ROLES = ("web-app-moodle", "web-app-nextcloud", "web-app-wordpress")


def declared_limits(role: str) -> dict:
    """Return a role's own `mcp.limits`, as its meta declares them.

    Args:
        role: the role directory name.
    """
    return load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MCP)["limits"]


def render(name: str, **context) -> str:
    """Return one template rendered with a stubbed `config` lookup.

    Args:
        name: template file name inside the MCP template directory.
        context: variables the template reads.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - nginx config, not markup; Ansible renders it the same way and HTML-escaping `$binary_remote_addr` would break it
    )
    return env.get_template(name).render(**context)


class TestZones(unittest.TestCase):
    def test_the_rate_follows_the_declared_concurrency(self):
        limits = declared_limits("web-app-moodle")
        rendered = render(
            "zones.conf.j2",
            application_id="web-app-moodle",
            lookup=lambda *_a, **_k: limits,
        )
        self.assertIn(
            f"rate={limits['concurrent_requests']}r/s",
            rendered,
        )

    def test_each_role_gets_a_zone_name_of_its_own(self):
        rendered = render(
            "zones.conf.j2",
            application_id="web-app-moodle",
            lookup=lambda *_a, **_k: declared_limits("web-app-moodle"),
        )
        self.assertIn("zone=mcp_web_app_moodle_req:10m", rendered)
        self.assertIn("zone=mcp_web_app_moodle_conn:10m", rendered)

    def test_the_two_zone_kinds_never_share_a_name(self):
        """nginx refuses a `limit_conn_zone` reusing a `limit_req_zone` name."""
        rendered = render(
            "zones.conf.j2",
            application_id="web-app-nextcloud",
            lookup=lambda *_a, **_k: declared_limits("web-app-nextcloud"),
        )
        names = [
            part.split(":", 1)[0]
            for line in rendered.splitlines()
            for part in line.split()
            if part.startswith("zone=")
        ]
        self.assertEqual(len(names), len(set(names)))

    def test_every_public_role_renders_a_zone_pair(self):
        for role in PUBLIC_ROLES:
            with self.subTest(role=role):
                rendered = render(
                    "zones.conf.j2",
                    application_id=role,
                    lookup=lambda *_a, _r=role, **_k: declared_limits(_r),
                )
                self.assertIn("limit_req_zone", rendered)
                self.assertIn("limit_conn_zone", rendered)


class TestDirectives(unittest.TestCase):
    def context(self, role: str) -> dict:
        return {
            "mcp_zone": "mcp_" + role.replace("-", "_"),
            "mcp_limits": declared_limits(role),
        }

    def test_the_connection_ceiling_is_the_declared_concurrency(self):
        limits = declared_limits("web-app-nextcloud")
        rendered = render("directives.conf.j2", **self.context("web-app-nextcloud"))
        self.assertIn(
            f"limit_conn mcp_web_app_nextcloud_conn {limits['concurrent_requests']};",
            rendered,
        )

    def test_the_burst_matches_the_ceiling_so_a_legal_client_is_never_delayed(self):
        limits = declared_limits("web-app-moodle")
        rendered = render("directives.conf.j2", **self.context("web-app-moodle"))
        self.assertIn(
            f"burst={limits['concurrent_requests']} nodelay;",
            rendered,
        )

    def test_a_refusal_is_429_rather_than_the_nginx_default_503(self):
        """503 reads as an outage; a client that backs off needs 429."""
        rendered = render("directives.conf.j2", **self.context("web-app-moodle"))
        self.assertIn("limit_req_status  429;", rendered)
        self.assertIn("limit_conn_status 429;", rendered)

    def test_the_directives_reference_the_zones_the_zone_file_declares(self):
        for role in PUBLIC_ROLES:
            with self.subTest(role=role):
                zone = "mcp_" + role.replace("-", "_")
                zones = render(
                    "zones.conf.j2",
                    application_id=role,
                    lookup=lambda *_a, _r=role, **_k: declared_limits(_r),
                )
                directives = render("directives.conf.j2", **self.context(role))
                self.assertIn(f"zone={zone}_req:", zones)
                self.assertIn(f"zone={zone}_req ", directives)
                self.assertIn(f"zone={zone}_conn:", zones)
                self.assertIn(f"{zone}_conn ", directives)


class TestPublicSurfacesAreCovered(unittest.TestCase):
    def test_the_pinned_roles_are_exactly_the_public_ones(self):
        """A new public surface must not reach the edge without these limits."""
        found = set()
        for meta in (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_MCP}"):
            if load_yaml(meta).get("exposure") == "public":
                found.add(meta.parent.parent.name)
        self.assertEqual(found, set(PUBLIC_ROLES))


def endpoint_roles() -> dict[str, dict]:
    """Return every role declaring an MCP endpoint path, by role name."""
    found = {}
    for meta in (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_MCP}"):
        block = load_yaml(meta)
        if (block.get("endpoint") or {}).get("path"):
            found[meta.parent.parent.name] = block
    return found


class TestTheAppVhostServesOnlyPublicSurfaces(unittest.TestCase):
    """`vhost.conf.j2` serves the MCP path, or returns 404 for it.

    A surface reachable on the application's own public vhost while the
    service is off, or while its declared exposure is internal, is a surface
    nobody decided to publish. For an adapter-fronted provider it is worse
    than untidy: the adapter exists to narrow the upstream's tool set, and a
    publicly routed native path walks straight past it.
    """

    def served(self, block: dict) -> bool:
        return bool(block.get("enabled")) and block.get("exposure") == "public"

    def test_an_internal_surface_is_not_served_on_the_public_vhost(self):
        for role, block in endpoint_roles().items():
            if block.get("exposure") != "public":
                with self.subTest(role=role):
                    self.assertFalse(self.served(block))

    def test_the_adapter_fronted_provider_hides_its_native_path(self):
        """Reaching baserow's own endpoint would bypass the four-tool contract."""
        block = endpoint_roles()["web-app-baserow"]
        self.assertEqual("adapter_server", block["classification"])
        self.assertFalse(self.served(block))

    def test_a_disabled_surface_is_never_served(self):
        for role, block in endpoint_roles().items():
            if not block.get("enabled"):
                with self.subTest(role=role):
                    self.assertFalse(self.served(block))

    def test_the_public_roles_are_the_only_ones_served(self):
        served = {r for r, b in endpoint_roles().items() if self.served(b)}
        self.assertEqual(served, {r for r in PUBLIC_ROLES if r != "web-app-wordpress"})


if __name__ == "__main__":
    unittest.main()
