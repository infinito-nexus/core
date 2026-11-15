from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.artefacts import url_for
from utils.cache.hosts import host_records, repo_records
from utils.cache.render import BACKEND, upstreams_conf
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers import ORDERED_HANDLERS
from utils.env.handlers.infinito.cache import artefact_base as handler

DEFAULT_SERVER = "listen 80 default_server;"
SHELL_DEFAULT = "https:/"
FRONTEND_IP = "172.30.0.4"
BLANK = {handler.KEY: "", handler.STACK_KEY: "", handler.FRONTEND_IP_KEY: ""}


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
            current = line.split()[1]
            found[current] = []
        elif line == "}":
            current = ""
        elif current:
            found[current].append(line)
    return found


def _base(stack: str) -> str:
    eb = EnvBuilder()
    eb.set(handler.STACK_KEY, stack)
    eb.set(handler.FRONTEND_IP_KEY, FRONTEND_IP)
    ctx = BuildContext(
        static={handler.KEY: SHELL_DEFAULT},
        static_comments={},
        repo_root=Path("/repo"),
        on_gha=False,
        on_act=False,
    )
    handler.apply(eb, ctx)
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
        self.assertEqual(set(self.locations), {f"/{name}/" for name in based})
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


class TestArtefactBase(unittest.TestCase):
    @patch.dict(os.environ, BLANK, clear=False)
    def test_the_cache_stack_points_the_base_at_the_frontend(self) -> None:
        self.assertEqual(_base("true"), f"http://{FRONTEND_IP}")

    @patch.dict(os.environ, BLANK, clear=False)
    def test_without_the_cache_stack_the_base_is_the_upstream(self) -> None:
        self.assertEqual(_base("false"), SHELL_DEFAULT)

    @patch.dict(os.environ, {**BLANK, handler.KEY: "https://mirror.example"})
    def test_an_exported_base_wins(self) -> None:
        self.assertEqual(_base("true"), "https://mirror.example")

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
