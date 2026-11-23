from __future__ import annotations

import re
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

_ROLE = PROJECT_ROOT / "roles/svc-ai-litellm"
_ENV_TEMPLATE = _ROLE / "templates/env.j2"
_PROXY_BASE_URL = re.compile(
    r"^PROXY_BASE_URL=\{\{\s*(?P<name>[A-Z_]+)\s*\}\}$", re.MULTILINE
)
_UI_ROLE = "web-app-litellm"
_ORIGIN = "https://llm.example"
_TLS_URLS = {"url.base": f"{_ORIGIN}/", "url.origin": _ORIGIN}


def _lookup(plugin: str, role: str, key: str) -> str:
    """
    Args:
      plugin: lookup plugin name, only "tls" is served.
      role: application id, only the UI role is served.
      key: "url.base" or "url.origin".

    Returns:
      the URL the tls lookup returns for that key.
    """
    if (plugin, role) != ("tls", _UI_ROLE):
        raise AssertionError(f"unexpected lookup({plugin!r}, {role!r}, {key!r})")
    return _TLS_URLS[key]


class TestProxyBaseUrl(unittest.TestCase):
    def test_the_fallback_form_posts_to_the_login_route(self) -> None:
        match = _PROXY_BASE_URL.search(read_text(str(_ENV_TEMPLATE)))
        self.assertIsNotNone(match, "env.j2 must set PROXY_BASE_URL from one variable")
        source = load_yaml(str(_ROLE / ROLE_FILE_VARS_MAIN))[match.group("name")]
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        proxy_base_url = env.from_string(source).render(
            lookup=_lookup, LITELLM_UI_ROLE=_UI_ROLE
        )
        self.assertEqual(f"{proxy_base_url}/login", f"{_ORIGIN}/login")


if __name__ == "__main__":
    unittest.main()
