from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.artefacts import url_for
from utils.cache.hosts import host_records, repo_records
from utils.cache.render import BACKEND, ROLE_DIR, upstreams_conf
from utils.cache.yaml import load_yaml
from utils.env.builder import apply_custom_env
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import ORDERED_HANDLERS
from utils.env.handlers.infinito.cache import artefact_base as handler
from utils.roles.mapping import ROLE_FILE_META_SERVICES

DEFAULT_SERVER_PORT = "80"
DEFAULT_SERVER = f"listen {DEFAULT_SERVER_PORT} default_server;"
SHELL_DEFAULT = "https:/"
FRONTEND_IP = "172.30.0.4"
BLANK = {handler.KEY: "", handler.STACK_KEY: "", handler.FRONTEND_IP_KEY: ""}
HEALTHY_ANSWER = "return 200;"
EXACT = "= "


def _base_block() -> str:
    blocks = [
        block for block in upstreams_conf().split("server {") if DEFAULT_SERVER in block
    ]
    if len(blocks) != 1:
        raise AssertionError(f"{len(blocks)} server blocks carry {DEFAULT_SERVER}")
    return blocks[0]


def _locations(block: str) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    current = ""
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith("location ") and line.endswith("{"):
            current = line.removeprefix("location ").removesuffix("{").strip()
            found[current] = []
        elif line == "}":
            current = ""
        elif current:
            found[current].append(line)
    return found


def _route(locations: dict[str, list[str]], path: str) -> list[str] | None:
    """Args:
        locations: the server block's locations, as ``_locations`` keys them.
        path: the request path.

    Returns:
        The directives of the location nginx picks for *path* (exact match,
        else longest prefix), None when none matches and nginx falls back to
        its static root.
    """
    if f"{EXACT}{path}" in locations:
        return locations[f"{EXACT}{path}"]
    prefixes = [
        key for key in locations if not key.startswith(EXACT) and path.startswith(key)
    ]
    return locations[max(prefixes, key=len)] if prefixes else None


def _frontend_probe() -> tuple[str, str]:
    """Returns:
    The internal port and the request path of the frontend's healthcheck.
    """
    frontend = load_yaml(str(ROLE_DIR / ROLE_FILE_META_SERVICES))["frontend"]
    healthcheck = frontend["healthcheck"]
    port = frontend["ports"]["internal"][healthcheck["port_key"]]
    return str(port), f"/{healthcheck.get('path', '')}"


def _base(stack: str, root: Path = Path("/repo")) -> str:
    eb = EnvBuilder()
    eb.set(handler.STACK_KEY, stack)
    eb.set(handler.FRONTEND_IP_KEY, FRONTEND_IP)
    ctx = BuildContext(
        static={handler.KEY: SHELL_DEFAULT},
        static_comments={},
        repo_root=root,
        on_gha=False,
        on_act=False,
    )
    handler.apply(eb, ctx)
    apply_custom_env(eb, root)
    return eb.values[handler.KEY]


class TestFrontendRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.records = host_records()
        self.repos = repo_records()
        self.locations = _locations(_base_block())

    def test_every_tls_or_unhijacked_host_is_routed_to_its_repository(
        self,
    ) -> None:
        based = {
            name: record
            for name, record in self.records.items()
            if record["tls"] or not record["hijack"]
        }
        self.assertTrue(any(not record["hijack"] for record in based.values()))
        _, probe_path = _frontend_probe()
        self.assertEqual(
            set(self.locations),
            {f"{EXACT}{probe_path}", *(f"/{name}/" for name in based)},
        )
        for name, record in based.items():
            with self.subTest(host=name):
                repo = self.repos[record["repo"]]["name"]
                self.assertIn(
                    f"proxy_pass {BACKEND}/repository/{repo}/;",
                    self.locations[f"/{name}/"],
                )

    def test_a_long_read_timeout_follows_the_host(self) -> None:
        timed = {
            name: record["read_timeout"]
            for name, record in self.records.items()
            if record["tls"] and record["read_timeout"]
        }
        self.assertTrue(timed)
        for name, timeout in timed.items():
            with self.subTest(host=name):
                self.assertIn(
                    f"proxy_read_timeout {timeout};", self.locations[f"/{name}/"]
                )

    def test_the_base_url_reaches_the_upstream_file_through_the_same_repository(
        self,
    ) -> None:
        base = f"http://{FRONTEND_IP}"
        rooted = [
            (name, self.repos[record["repo"]])
            for name, record in self.records.items()
            if (record["tls"] or not record["hijack"])
            and self.repos[record["repo"]]["upstream"] == f"https://{name}/"
        ]
        self.assertTrue(rooted)
        for name, repo in rooted:
            with self.subTest(host=name):
                upstream = f"https://{name}/org/file.bin"
                fetched = url_for(upstream, base).removeprefix(base)
                location = f"/{name}/"
                self.assertTrue(fetched.startswith(location))
                backend = f"{BACKEND}/repository/{repo['name']}/"
                self.assertIn(f"proxy_pass {backend};", self.locations[location])
                remainder = fetched.removeprefix(location)
                self.assertEqual(repo["upstream"] + remainder, upstream)

    def test_exactly_one_server_is_the_port_80_default(self) -> None:
        self.assertEqual(upstreams_conf().count("default_server"), 1)

    def test_the_default_server_answers_the_frontend_healthcheck(self) -> None:
        port, path = _frontend_probe()
        self.assertEqual(port, DEFAULT_SERVER_PORT)
        self.assertEqual(
            _route(self.locations, path),
            [HEALTHY_ANSWER],
            "the probe addresses the frontend by IP, which no server_name names, "
            "so the default server answers it; without a route there nginx serves "
            "its static root and the container never turns healthy",
        )

    def test_negative_control_a_default_server_without_the_route_fails_the_probe(
        self,
    ) -> None:
        _, path = _frontend_probe()
        bare = {
            key: body for key, body in self.locations.items() if key != f"{EXACT}{path}"
        }
        self.assertIsNone(_route(bare, path))
        self.assertEqual(
            _route({**bare, path: [HEALTHY_ANSWER]}, path),
            [HEALTHY_ANSWER],
        )


class TestArtefactBase(unittest.TestCase):
    @patch.dict(os.environ, BLANK, clear=False)
    def test_the_cache_stack_points_the_base_at_the_frontend(self) -> None:
        self.assertEqual(_base("true"), f"http://{FRONTEND_IP}")

    @patch.dict(os.environ, BLANK, clear=False)
    def test_without_the_cache_stack_the_base_is_the_upstream(self) -> None:
        self.assertEqual(_base("false"), SHELL_DEFAULT)

    @patch.dict(os.environ, {**BLANK, handler.KEY: f"http://{FRONTEND_IP}"})
    def test_a_stale_frontend_base_is_recomputed_once_the_stack_is_off(
        self,
    ) -> None:
        self.assertEqual(_base("false"), SHELL_DEFAULT)

    @patch.dict(os.environ, {**BLANK, handler.KEY: SHELL_DEFAULT})
    def test_a_stale_upstream_base_is_recomputed_once_the_stack_is_on(
        self,
    ) -> None:
        self.assertEqual(_base("true"), f"http://{FRONTEND_IP}")

    @patch.dict(os.environ, BLANK, clear=False)
    def test_a_custom_env_base_wins(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "custom.env").write_text(
                f"{handler.KEY}=https://mirror.example\n", encoding="utf-8"
            )
            self.assertEqual(_base("true", Path(root)), "https://mirror.example")

    def test_the_handler_runs_after_the_stack_and_the_frontend_address(
        self,
    ) -> None:
        names = [module.__name__.rsplit(".", 1)[-1] for module in ORDERED_HANDLERS]
        self.assertLess(names.index("stack"), names.index("artefact_base"))
        self.assertLess(names.index("passthrough"), names.index("artefact_base"))

    @patch.dict(os.environ, BLANK, clear=False)
    def test_the_frontend_base_is_one_url_for_accepts(self) -> None:
        url = "https://huggingface.co/org/repo/resolve/main/file.bin"
        self.assertEqual(
            url_for(url, _base("true")),
            f"http://{FRONTEND_IP}/huggingface.co/org/repo/resolve/main/file.bin",
        )


if __name__ == "__main__":
    unittest.main()
