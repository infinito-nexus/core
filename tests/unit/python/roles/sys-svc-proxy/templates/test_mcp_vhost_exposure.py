"""An internal MCP surface is withdrawn from the edge under every spelling.

The adapter exists to narrow an upstream's tool set, so a publicly routed
native path walks straight past it. `mcp/vhost.conf.j2` withdraws such a path
with `return 404`, and the question this file answers is whether the withdrawal
covers the URLs the application actually answers.

It does not follow from the declared path alone. A front-controller application
serves one route under two spellings -- `/index.php/apps/…` and `/apps/…` --
and a prefix `location` for the first leaves the second reachable, because the
app's own `try_files … /index.php$request_uri` rewrites it back onto the route
after the edge has already decided not to block it. Nextcloud is the one
provider whose `adapter.upstream_path` carries the front controller today, so
the case is pinned here rather than left to the next reader to rediscover.

The sibling `test_mcp_edge_limits.py` pins the values a *public* surface is
served behind; this file pins what an *internal* one must not be served at.
"""

from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MCP

from . import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "roles/sys-svc-proxy/templates/mcp"

FRONT_CONTROLLER_ROLE = "web-app-nextcloud"


def meta(role: str) -> dict:
    """Return a role's `meta/mcp.yml`.

    Args:
        role: the role directory name.
    """
    return load_yaml(PROJECT_ROOT / "roles" / role / ROLE_FILE_META_MCP)


def render(role: str, *, exposure: str) -> str:
    """Return `vhost.conf.j2` for one role at one exposure.

    Args:
        role: the role directory name.
        exposure: the `mcp.exposure` value to render under.
    """
    block = meta(role)
    values = {
        "mcp.endpoint.path": block["endpoint"]["path"],
        "mcp.adapter.upstream_path": (block.get("adapter") or {}).get(
            "upstream_path", ""
        ),
        "mcp.exposure": exposure,
        "mcp.enabled": True,
        "mcp.limits": block["limits"],
    }

    def config(_app, key, default=None):
        return values.get(key, default)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 - nginx config, not markup; HTML-escaping would corrupt the directives
    )
    env.filters["regex_replace"] = lambda value, pattern, repl="": re.sub(
        pattern, repl, value
    )
    env.filters["regex_escape"] = re.escape
    return env.get_template("vhost.conf.j2").render(
        application_id=role,
        lookup=lambda kind, *args, **_kw: config(*args) if kind == "config" else "",
    )


def withdrawals(rendered: str) -> list[tuple[str, str]]:
    """Return `(kind, value)` for every `return 404` location.

    Args:
        rendered: the rendered vhost fragment.

    `kind` is `regex` for a `location ~ …` and `prefix` for a bare one, so a
    caller matches each the way nginx does rather than assuming one form.
    """
    return re.findall(r"location\s+(~)?\s*(\S+)\s*\{\s*return 404;", rendered)


def is_blocked(rendered: str, url_path: str) -> bool:
    """Return whether a request path matches any withdrawal.

    Args:
        rendered: the rendered vhost fragment.
        url_path: the path a client would request.
    """
    return any(
        re.match(value, url_path) if tilde else url_path.startswith(value)
        for tilde, value in withdrawals(rendered)
    )


class TestInternalSurfaceIsWithdrawn(unittest.TestCase):
    def test_both_declared_paths_are_withdrawn(self):
        block = meta(FRONT_CONTROLLER_ROLE)
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        for declared in (
            block["endpoint"]["path"],
            block["adapter"]["upstream_path"],
        ):
            with self.subTest(path=declared):
                self.assertTrue(
                    is_blocked(rendered, declared),
                    f"{declared} stays reachable at the edge",
                )

    def test_the_front_controller_alias_is_withdrawn_too(self):
        block = meta(FRONT_CONTROLLER_ROLE)
        alias = block["adapter"]["upstream_path"].replace("/index.php", "", 1)
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        self.assertTrue(
            is_blocked(rendered, alias),
            f"{alias} reaches the same route as the declared path and must be "
            f"withdrawn with it",
        )

    def test_the_withdrawal_does_not_reach_unrelated_paths(self):
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        for spared in ("/index.php/login", "/apps/files", "/status.php"):
            with self.subTest(path=spared):
                self.assertFalse(
                    is_blocked(rendered, spared),
                    f"{spared} is not an MCP path and must stay served",
                )

    def test_an_internal_surface_proxies_nothing(self):
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        self.assertNotIn("proxy_pass", rendered)

    def test_the_front_controller_path_is_withdrawn_as_a_regex(self):
        """A prefix location cannot cover both spellings; only a regex can."""
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        upstream = meta(FRONT_CONTROLLER_ROLE)["adapter"]["upstream_path"]
        covering = [
            value
            for tilde, value in withdrawals(rendered)
            if tilde and re.match(value, upstream)
        ]
        self.assertTrue(
            covering,
            f"{upstream} carries a front controller, so its withdrawal must be "
            f"a regex location",
        )

    def test_the_scan_finds_a_withdrawal(self):
        rendered = render(FRONT_CONTROLLER_ROLE, exposure="internal")
        self.assertTrue(
            withdrawals(rendered),
            "no withdrawal was rendered at all, so every assertion here would "
            "pass vacuously",
        )


if __name__ == "__main__":
    unittest.main()
