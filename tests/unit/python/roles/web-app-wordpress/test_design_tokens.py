from __future__ import annotations

import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.lookup.cdn import LookupModule as CdnLookup
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

VARS = PROJECT_ROOT / "roles" / "web-app-wordpress" / ROLE_FILE_VARS_MAIN
CDN_ROOT = "/var/www/public/cdn"
CDN_URL = "https://cdn.example.test/"


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms)]


def render_tokens() -> list[str]:
    """Render ``WORDPRESS_DESIGN_CONFIG.tokens`` through the real ``cdn`` lookup.

    Returns:
        The token stylesheet URLs the deploy writes into the ``infinito_design``
        option, with the CDN served at ``CDN_URL`` from ``CDN_ROOT``.
    """
    stubs = {"nginx": lambda _key: CDN_ROOT, "tls": lambda _app, _key: CDN_URL}
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "cdn":
            lookup = CdnLookup()
            lookup._loader = kwargs.get("loader")
            lookup._templar = None
            return lookup
        if name in stubs:
            return _Stub(stubs[name])
        return real_get(name, *args, **kwargs)

    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return [
            templar.template(token)
            for token in declared["WORDPRESS_DESIGN_CONFIG"]["tokens"]
        ]


class TestEditorCanvasTokens(unittest.TestCase):
    def test_the_token_sheets_load_from_the_page_host(self) -> None:
        self.assertEqual(
            render_tokens(),
            ["/_infinito/cdn/_shared/css/default.css"],
            "the option is written once for every network sibling, so an absolute CDN "
            "host sends the onion editor canvas to clearnet",
        )


if __name__ == "__main__":
    unittest.main()
