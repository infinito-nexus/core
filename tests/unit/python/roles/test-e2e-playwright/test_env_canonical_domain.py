from __future__ import annotations

import json
import unittest
from urllib.parse import urlsplit

from jinja2 import Environment, StrictUndefined

from plugins.filter.dotenv import dotenv_quote
from plugins.filter.network_of import in_network, network_of, network_suffixes
from plugins.lookup.network_siblings import served_siblings
from utils.cache.yaml import load_yaml_any
from utils.domains.default_primary import default_domain_primary

from . import PROJECT_ROOT

TASKS = PROJECT_ROOT / "roles/test-e2e-playwright/tasks/03_run_pass.yml"
TASK_NAME = "📄 Render .env from templates/playwright.env.j2"
PRIMARY = default_domain_primary()
NODE = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvw.onion"
CLEARNET = [f"api.s3.{PRIMARY}", f"console.s3.{PRIMARY}"]
TOR = [f"api.s3.{NODE}", f"console.s3.{NODE}"]


def render(pass_domain: str) -> str:
    tasks = load_yaml_any(str(TASKS))
    task = next(t for t in tasks if t.get("name") == TASK_NAME)
    env = Environment(autoescape=False, trim_blocks=True, undefined=StrictUndefined)  # noqa: S701 - dotenv file, not markup
    env.filters.update(
        dotenv_quote=dotenv_quote,
        in_network=in_network,
        network_of=network_of,
        network_suffixes=network_suffixes,
        to_json=json.dumps,
        urlsplit=lambda url, part: getattr(urlsplit(url), part),
    )

    def lookup(name, term, template_vars=None):
        if name == "template":
            return (
                f'APP_BASE_URL="https://{template_vars["domain"]}/"\n'
                f'CANONICAL_DOMAIN="{CLEARNET[1]}"\n'
            )
        return served_siblings(term, {"web-app-minio": CLEARNET + TOR}, PRIMARY, NODE)

    return env.from_string(task["ansible.builtin.copy"]["content"]).render(
        lookup=lookup,
        _playwright_env_template="playwright.env.j2",
        _playwright_pass_domain=pass_domain,
        _playwright_passes=[CLEARNET[0], TOR[0]],
        TEST_E2E_PLAYWRIGHT_CONFIG_TIMEOUTS={},
        OIDC={"URL": f"https://auth.{PRIMARY}/realms/main"},
        DEPLOYMENT_MODE="compose",
    )


class TestEnvCanonicalDomain(unittest.TestCase):
    def test_onion_pick_moves_the_canonical_domain_to_its_onion_sibling(self):
        rendered = render(TOR[0])
        self.assertIn(f'APP_BASE_URL="https://{TOR[0]}/"\n', rendered)
        self.assertIn(f'CANONICAL_DOMAIN="{TOR[1]}"\n', rendered)

    def test_canonical_network_pick_keeps_the_rendered_env(self):
        self.assertTrue(
            render(CLEARNET[0]).startswith(
                f'APP_BASE_URL="https://{CLEARNET[0]}/"\n'
                f'CANONICAL_DOMAIN="{CLEARNET[1]}"\n'
            )
        )


if __name__ == "__main__":
    unittest.main()
