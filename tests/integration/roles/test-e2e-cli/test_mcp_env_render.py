"""The shared MCP env template renders for every provider that has to run it.

``test.env`` is the whole interface between the deployment and the MCP CLI
test: the endpoint, the credential a client presents, the tool contract and the
networks the sidecar may hold all reach the checkers through it and through
nothing else. A key that fails to resolve does not announce itself there. It
arrives as the literal ``{{ ... }}`` source, the shell accepts it as a string,
and the check that reads it draws a conclusion from text nobody rendered.

The render runs through Ansible's own templar against the real resolved
applications map, so the lookups, filters and the nested ``lookup('template')``
are the ones the deploy uses rather than stand-ins for them.

``MCP_TEST_ENABLED`` gets its own check on top of that. It is derived from
``group_names`` rather than declared, so it is the one key that can arrive as
its own source, and a flag that is neither ``true`` nor ``false`` would switch
the whole suite off for every provider at once. Only one polarity is rendered:
the ``config`` lookup caches per process and stops reading ``group_names``
after the first resolution, so a second render in the same interpreter would
report the first answer whatever it is handed.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from collections.abc import Mapping
from urllib.parse import urlparse

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.applications import get_application_defaults
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_MCP,
    ROLE_FILE_META_TESTS,
    ROLE_FILE_VARS_MAIN,
)

_SHARED = "roles/test-e2e-cli/templates/mcp/test.env.j2"
_DOMAIN = "infinito.test"
_SERVER_DIRECTIONS = frozenset({"server", "both"})
_CLIENT_DIRECTIONS = frozenset({"client"})
_MODES = ("compose", "swarm")
_CONSUMERS = (
    "web-app-flowise",
    "web-app-hermes",
    "web-app-openclaw",
    "web-app-openwebui",
)
_REQUIRED = (
    "MCP_AUTH_HEADER",
    "MCP_DEADLINE_SECONDS",
    "MCP_DEPLOYMENT_MODE",
    "MCP_EXPECTED_NETWORKS",
    "MCP_EXPECTED_TOOLS",
    "MCP_TEST_ENABLED",
    "MCP_TEST_IMAGE",
    "MCP_TEST_NETWORK",
    "MCP_TRANSPORT",
    "MCP_URL",
)


def _roles_with_direction(directions: frozenset[str]) -> list[str]:
    """Return the role ids whose ``meta/mcp.yml`` declares one of ``directions``."""
    roles_root = PROJECT_ROOT / "roles"
    found: list[str] = []
    for mcp_path in sorted(roles_root.glob(f"*/{ROLE_FILE_META_MCP}")):
        mcp = load_yaml_any(str(mcp_path), default_if_missing={})
        if not isinstance(mcp, Mapping):
            continue
        if str(mcp.get("direction") or "").strip().lower() in directions:
            found.append(mcp_path.parent.parent.name)
    return found


def _providers() -> list[str]:
    """Return the role ids that serve an MCP endpoint."""
    return _roles_with_direction(_SERVER_DIRECTIONS)


def _clients() -> list[str]:
    """Return the client role ids that ship a CLI test env template."""
    return [
        role
        for role in _roles_with_direction(_CLIENT_DIRECTIONS)
        if (PROJECT_ROOT / "roles" / role / "templates/test.env.j2").is_file()
    ]


def _trusted(value: object) -> object:
    """Trust nested strings so a loaded var that carries Jinja still templates."""
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, Mapping):
        return {k: _trusted(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trusted(v) for v in value]
    return value


def _group_vars_all() -> dict:
    """The ``group_vars/all`` layer every play carries under the role vars."""
    loaded: dict = {}
    for path in sorted((PROJECT_ROOT / "group_vars/all").glob("*.yml")):
        data = load_yaml_any(str(path), default_if_missing={})
        if isinstance(data, Mapping):
            loaded.update({k: _trusted(v) for k, v in data.items()})
    return loaded


def _role_scoped_vars(application_id: str) -> dict:
    """Mirror the ``include_vars`` chain ``run_one.yml:44-70`` runs before rendering."""
    loaded: dict = {}
    for candidate in (
        PROJECT_ROOT / "roles" / application_id / ROLE_FILE_DEFAULTS_MAIN,
        PROJECT_ROOT / "roles" / application_id / ROLE_FILE_VARS_MAIN,
    ):
        if not candidate.is_file():
            continue
        data = load_yaml_any(str(candidate), default_if_missing={})
        if isinstance(data, Mapping):
            loaded.update({k: _trusted(v) for k, v in data.items()})
    return loaded


def _render(
    application_id: str, group_names: list[str], mode: str = "compose"
) -> str:
    """Render the role's own env template the way ``run_one.yml`` does."""
    role_template = PROJECT_ROOT / "roles" / application_id / "templates/test.env.j2"
    variables = {
        **_group_vars_all(),
        **_role_scoped_vars(application_id),
        "applications": get_application_defaults(roles_dir=PROJECT_ROOT / "roles"),
        "application_id": application_id,
        "group_names": group_names,
        "playbook_dir": str(PROJECT_ROOT),
        "compose_mode": mode,
        "DEPLOYMENT_MODE": mode,
        "TIMEOUT_FACTOR": 1,
        "PRIMARY_DOMAIN": _DOMAIN,
        "DOMAIN_PRIMARY": _DOMAIN,
        "SYSTEM_EMAIL_DOMAIN": _DOMAIN,
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(
        trust_as_template(f"{{{{ lookup('template', '{role_template.resolve()}') }}}}")
    )


def _entries(rendered: str) -> dict[str, str]:
    """Return the KEY=value pairs a shell would read out of the rendering."""
    pairs: dict[str, str] = {}
    for line in rendered.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise AssertionError(f"not a KEY=value line: {line!r}")
        pairs[key] = value
    return pairs


class TestMcpEnvRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.providers = _providers()
        cls.on = {p: _render(p, [*_CONSUMERS, p]) for p in cls.providers}

    def test_the_scan_finds_providers(self) -> None:
        self.assertTrue(self.providers)
        self.assertEqual(
            [],
            [
                p
                for p in self.providers
                if not (PROJECT_ROOT / "roles" / p / "templates/test.env.j2").is_file()
            ],
        )

    def test_every_role_renders_the_shared_template(self) -> None:
        shared = read_text(str(PROJECT_ROOT / _SHARED))
        keys = sorted(
            line.split("=", 1)[0]
            for line in shared.splitlines()
            if line and not line.startswith("{%")
        )
        for provider, rendered in self.on.items():
            with self.subTest(provider=provider):
                self.assertEqual(keys, sorted(_entries(rendered)))

    def test_nothing_reaches_the_shell_unrendered(self) -> None:
        for provider, rendered in self.on.items():
            with self.subTest(provider=provider):
                leaked = [k for k, v in _entries(rendered).items() if "{{" in v]
                self.assertEqual([], leaked)

    def test_the_required_keys_are_non_empty(self) -> None:
        for provider, rendered in self.on.items():
            entries = _entries(rendered)
            with self.subTest(provider=provider):
                self.assertEqual(
                    [], [k for k in _REQUIRED if not entries[k].strip("'")]
                )

    def test_the_flag_resolves_to_a_boolean(self) -> None:
        for provider, rendered in self.on.items():
            with self.subTest(provider=provider):
                self.assertIn(_entries(rendered)["MCP_TEST_ENABLED"], ("true", "false"))

    def test_the_endpoint_url_is_addressable(self) -> None:
        for provider, rendered in self.on.items():
            with self.subTest(provider=provider):
                parsed = urlparse(_entries(rendered)["MCP_URL"])
                self.assertEqual("http", parsed.scheme)
                self.assertTrue(parsed.hostname)
                self.assertTrue(parsed.port)
                self.assertTrue(parsed.path)

    def test_the_read_probe_is_inside_the_served_contract(self) -> None:
        for provider, rendered in self.on.items():
            entries = _entries(rendered)
            tool = entries["MCP_READ_TOOL"]
            allowlist = json.loads(entries["MCP_EXPECTED_TOOLS"].strip("'"))
            with self.subTest(provider=provider):
                if tool and allowlist:
                    self.assertIn(tool, allowlist)

    def test_the_deadline_stays_under_the_harness_timeout(self) -> None:
        for provider, rendered in self.on.items():
            budget = load_yaml_any(
                str(PROJECT_ROOT / "roles" / provider / ROLE_FILE_META_TESTS),
                default_if_missing={},
            )
            with self.subTest(provider=provider):
                deadline = int(_entries(rendered)["MCP_DEADLINE_SECONDS"])
                self.assertLess(deadline, int(budget["cli"]["timeout"]))

    def test_a_shell_reads_every_value_back_whole(self) -> None:
        for provider, rendered in self.on.items():
            entries = _entries(rendered)
            script = "set -a\n. /dev/stdin\nset +a\n" + "".join(
                f'printf "%s\\n" "${{{key}}}"\n' for key in sorted(entries)
            )
            with self.subTest(provider=provider):
                result = subprocess.run(
                    ["/bin/bash", "-c", script],
                    input=rendered,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual(
                    [entries[k].strip("'") for k in sorted(entries)],
                    result.stdout.splitlines(),
                )


class TestMcpClientEnvRender(unittest.TestCase):
    """The client half of the same interface, in both deployment modes.

    ``_providers`` covers the roles that serve an endpoint. The roles that
    consume one render their own ``test.env.j2`` through the same path and were
    covered by nothing, in either mode, so the swarm branch of
    ``lookup('container_address')`` was never exercised under ``tests/``.
    ``container_address`` reads ``DEPLOYMENT_MODE`` straight from the templar
    variables, so both modes can be rendered in one interpreter; the per-process
    ``config`` cache that limits the provider suite to one polarity does not
    reach the mode split.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.clients = _clients()
        cls.rendered = {
            (client, mode): _render(client, [*_CONSUMERS, client], mode)
            for client in cls.clients
            for mode in _MODES
        }

    def test_the_scan_finds_clients_with_a_cli_test(self) -> None:
        self.assertTrue(self.clients)

    def test_nothing_reaches_the_shell_unrendered(self) -> None:
        for (client, mode), rendered in self.rendered.items():
            with self.subTest(client=client, mode=mode):
                leaked = [k for k, v in _entries(rendered).items() if "{{" in v]
                self.assertEqual([], leaked)

    def test_every_key_resolves_to_something(self) -> None:
        for (client, mode), rendered in self.rendered.items():
            entries = _entries(rendered)
            with self.subTest(client=client, mode=mode):
                self.assertTrue(entries)
                self.assertEqual(
                    [], [k for k, v in entries.items() if not v.strip("'")]
                )

    def test_the_flag_resolves_to_a_boolean(self) -> None:
        for (client, mode), rendered in self.rendered.items():
            with self.subTest(client=client, mode=mode):
                self.assertIn(_entries(rendered)["MCP_TEST_ENABLED"], ("true", "false"))


if __name__ == "__main__":
    unittest.main()
