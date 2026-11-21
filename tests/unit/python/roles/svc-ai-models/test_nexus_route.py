from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from plugins.lookup.cache_artefacts import LookupModule
from utils import PROJECT_ROOT
from utils.cache.artefacts import records, url_for
from utils.cache.hosts import host_records
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

ROLE = PROJECT_ROOT / "roles" / "svc-ai-models"
INVENTORY = PROJECT_ROOT / "inventories" / "development" / "default.yml"
KEY = "INFINITO_ARTEFACT_BASE"
FRONTEND = "http://10.47.0.2"
SHELL_DEFAULT = "https:/"
TODAY_SEED = "{{ models_seeded }}"


def _role_base() -> str:
    services = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))
    return services["models"]["artefact_base"]


def _texts() -> tuple[str, str]:
    applications = load_yaml(str(INVENTORY))["applications"]
    [seed] = load_yaml_any(str(ROLE / "tasks" / "utils" / "seed.yml"))
    return (
        applications["svc-ai-models"]["services"]["models"]["artefact_base"],
        seed["artefact_store"]["artefacts"],
    )


def _base(raw: str, environ: dict[str, str]) -> str:
    env = Environment(autoescape=select_autoescape(default_for_string=False))

    def lookup(name: str, key: str) -> str:
        if name != "env":
            raise KeyError(name)
        return environ.get(key, "")

    env.globals["lookup"] = lookup
    return env.from_string(raw).render()


def _seeded(expression: str, base: str, seeded: list[dict]) -> list[dict]:
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())

    def lookup(name: str, *terms: str, **kwargs: str) -> dict:
        if name != "cache_artefacts":
            raise KeyError(name)
        return LookupModule().run(list(terms), **kwargs)[0]

    env.globals["lookup"] = lookup
    return env.from_string(expression).render(
        MODELS_ARTEFACT_BASE=base, models_seeded=seeded
    )


def _findings(raw_base: str, expression: str, environ: dict[str, str]) -> list[str]:
    expected = environ.get(KEY, "")
    base = _base(raw_base, environ)
    found = [] if base == expected else [f"artefact_base is {base!r}, not {KEY}"]
    upstream = list(records("").values())
    fetched = {
        record["name"]: record["url"] for record in _seeded(expression, base, upstream)
    }
    found.extend(
        f"{record['name']} is fetched from {fetched.get(record['name'])}"
        for record in upstream
        if fetched.get(record["name"]) != url_for(record["upstream"], expected)
    )
    return found


class TestPrefetchThroughNexus(unittest.TestCase):
    def test_the_prefetch_fetches_every_artefact_through_the_frontend(self) -> None:
        self.assertEqual(_findings(*_texts(), {KEY: FRONTEND}), [])

    def test_every_fetched_url_reaches_a_host_the_frontend_routes_to_nexus(
        self,
    ) -> None:
        routed = {
            name
            for name, record in host_records().items()
            if record["tls"] or not record["hijack"]
        }
        _, expression = _texts()
        fetched = _seeded(expression, FRONTEND, list(records("").values()))
        self.assertTrue(fetched)
        for record in fetched:
            with self.subTest(artefact=record["name"]):
                host = urlsplit(record["upstream"]).hostname
                self.assertTrue(record["url"].startswith(f"{FRONTEND}/{host}/"))
                self.assertIn(host, routed)

    def test_without_the_cache_stack_the_prefetch_keeps_the_upstream(self) -> None:
        raw_base, expression = _texts()
        for environ in ({KEY: SHELL_DEFAULT}, {}):
            with self.subTest(environ=environ):
                self.assertEqual(_findings(raw_base, expression, environ), [])
                base = _base(raw_base, environ)
                for record in _seeded(expression, base, list(records("").values())):
                    self.assertEqual(record["url"], record["upstream"])

    def test_the_deploy_container_receives_the_base(self) -> None:
        compose = load_yaml(str(PROJECT_ROOT / "compose.yml"))
        environment = compose["services"]["infinito"]["environment"]
        self.assertEqual(environment[KEY], f"${{{KEY}}}")

    def test_the_role_itself_fetches_from_the_upstream(self) -> None:
        self.assertEqual(_role_base(), "")

    def test_the_guard_reports_an_empty_base_and_a_seed_of_the_callers_urls(
        self,
    ) -> None:
        raw_base, expression = _texts()
        self.assertEqual(_findings(raw_base, expression, {KEY: FRONTEND}), [])
        empty = _findings(_role_base(), expression, {KEY: FRONTEND})
        self.assertIn(f"artefact_base is '', not {KEY}", empty)
        upstream = _findings(raw_base, TODAY_SEED, {KEY: FRONTEND})
        self.assertEqual(len(upstream), len(records("")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
