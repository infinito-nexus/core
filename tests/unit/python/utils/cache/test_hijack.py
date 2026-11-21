from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache import artefacts, pin
from utils.cache.hosts import (
    HTTP_PORT,
    HTTPS_PORT,
    CachedHost,
    _hijack,
    declarations,
    host_records,
)
from utils.cache.render import BACKEND, cache_consumer_yml, upstreams_conf
from utils.env.context import BuildContext, EnvBuilder
from utils.env.handlers.infinito.cache import hosts as hosts_handler
from utils.env.handlers.infinito.cache import http_hosts, tls

GITHUB = artefacts.GITHUB
GITHUB_REPO = "raw-github"
ENGINE = "svc-ai-libretranslate-engine"
HIJACKED = artefacts.HUB
RELEASE_PATH = "LibreTranslate/MiniSBD/releases/download/v0.0.1/en.onnx"
MINISBD_URL = f"https://{GITHUB}/{RELEASE_PATH}"
BASE = "http://172.30.0.4"
DIGEST = "f7ede42862ceca07ad1c88a97b67520019c4ac7e5ced250d2e696fa62ab189af"
DEFAULT_SERVER = "listen 80 default_server;"


def _env(handler) -> list[str]:
    eb = EnvBuilder()
    handler.apply(
        eb,
        BuildContext(
            static={},
            static_comments={},
            repo_root=Path("/repo"),
            on_gha=False,
            on_act=False,
        ),
    )
    return eb.values[handler.KEY].replace(",", " ").split()


def _server(name: str) -> str:
    return next(
        block
        for block in upstreams_conf().split("server {")
        if f"server_name {name};" in block
    )


def _base_block() -> str:
    return next(
        block for block in upstreams_conf().split("server {") if DEFAULT_SERVER in block
    )


class TestCachedHost(unittest.TestCase):
    def test_an_unhijacked_host_has_no_listener_but_the_base_route(self) -> None:
        entry = CachedHost(GITHUB, repo=GITHUB_REPO, hijack=False)
        self.assertEqual(entry.listeners(), ())
        self.assertFalse(entry.tls())
        self.assertTrue(entry.at_base())

    def test_a_hijacked_host_keeps_its_listeners(self) -> None:
        entry = CachedHost(HIJACKED, repo="raw-huggingface")
        self.assertEqual(entry.listeners(), ((HTTPS_PORT, True),))
        self.assertTrue(entry.at_base())
        plain = CachedHost(HIJACKED, repo="raw-huggingface", listen=(HTTP_PORT,))
        self.assertEqual(plain.listeners(), ((HTTP_PORT, False),))
        self.assertFalse(plain.at_base())

    def test_the_flag_is_a_true_or_false_string_defaulting_to_true(self) -> None:
        self.assertTrue(_hijack(GITHUB, {}))
        self.assertTrue(_hijack(GITHUB, {"hijack": "true"}))
        self.assertFalse(_hijack(GITHUB, {"hijack": "false"}))
        for typo in ("flase", "no", ""):
            with self.subTest(value=typo), self.assertRaisesRegex(ValueError, GITHUB):
                _hijack(GITHUB, {"hijack": typo})


class TestGithubDeclaration(unittest.TestCase):
    def test_github_is_declared_unhijacked_by_the_engine(self) -> None:
        entry = next(e for e in declarations().hosts if e.host == GITHUB)
        self.assertEqual(
            (entry.role, entry.repo, entry.hijack), (ENGINE, GITHUB_REPO, False)
        )

    def test_github_never_lands_in_extra_hosts_or_a_leaf_certificate(self) -> None:
        for handler in (hosts_handler, tls, http_hosts):
            with self.subTest(key=handler.KEY):
                self.assertNotIn(GITHUB, _env(handler))
        self.assertNotIn(f'"{GITHUB}:', cache_consumer_yml())
        self.assertNotIn(f"server_name {GITHUB};", upstreams_conf())
        self.assertNotIn(f"/{GITHUB}.crt;", upstreams_conf())

    def test_the_release_download_route_reaches_the_raw_github_repository(self) -> None:
        fetched = artefacts.url_for(MINISBD_URL, BASE).removeprefix(BASE)
        location = f"/{GITHUB}/"
        self.assertTrue(
            fetched.startswith(f"{location}LibreTranslate/MiniSBD/releases/download/")
        )
        block = _base_block()
        self.assertIn(f"location {location} {{", block)
        route = block.split(f"location {location} {{", 1)[1].split("}", 1)[0]
        self.assertIn(f"proxy_pass {BACKEND}/repository/{GITHUB_REPO}/;", route)

    def test_the_contract_accepts_a_minisbd_asset_routed_through_it(self) -> None:
        asset = artefacts.Artefact(
            name="minisbd-en",
            url=MINISBD_URL,
            revision="v0.0.1",
            sha256=DIGEST,
            size="1",
            role=ENGINE,
        )
        self.assertEqual(artefacts.problems(asset, declarations()), [])


class TestHijackedHostUnchanged(unittest.TestCase):
    def test_a_hijacked_tls_host_keeps_extra_hosts_certificate_and_listener(
        self,
    ) -> None:
        self.assertIn(HIJACKED, _env(hosts_handler))
        self.assertIn(HIJACKED, _env(tls))
        self.assertIn(f'"{HIJACKED}:', cache_consumer_yml())
        server = _server(HIJACKED)
        self.assertIn(f"listen {HTTPS_PORT} ssl;", server)
        self.assertIn(f"/{HIJACKED}.crt;", server)
        self.assertIn(f"location /{HIJACKED}/ {{", _base_block())

    def test_every_plain_http_host_stays_hijacked(self) -> None:
        plain = {
            name
            for name, record in host_records().items()
            if any(listener["port"] == HTTP_PORT for listener in record["listen"])
        }
        self.assertTrue(plain)
        self.assertEqual(set(_env(http_hosts)), plain)
        self.assertLessEqual(plain, set(_env(hosts_handler)))


class TestPin(unittest.TestCase):
    def setUp(self) -> None:
        self.own = host_records()
        self.before = {
            name: {k: v for k, v in record.items() if k != "hijack"}
            for name, record in self.own.items()
        }

    def test_a_pin_predating_the_flag_agrees_on_every_hijacked_host(self) -> None:
        hijacked = {name for name, record in self.own.items() if record["hijack"]}
        self.assertEqual(pin.agreed(self.own, self.before), hijacked)

    def test_an_unhijacked_host_differs_from_a_pin_lacking_the_flag(self) -> None:
        self.assertEqual(
            pin.drift({"hosts": self.own}, {"hosts": self.before}),
            [f"host {GITHUB}: declared differently here"],
        )


if __name__ == "__main__":
    unittest.main()
