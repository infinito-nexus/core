from __future__ import annotations

import unittest
from urllib.parse import urlsplit

from plugins.filter.mirror_filters import external_asset_origins
from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.domains.default_primary import default_domain_primary
from utils.roles.mapping import ROLE_FILE_META_CSP

APPLICATION_ID = "web-app-map-animator"
CSP = PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_CSP
UPSTREAM_PAGE_ASSETS = ("https://versatiles.org/assets/logo/versatiles.32.png",)


def _mirror_origins() -> list[str]:
    applications = {APPLICATION_ID: {"csp": load_yaml(CSP)}}
    return external_asset_origins(
        applications, APPLICATION_ID, default_domain_primary()
    )


class TestOnionAssetMirror(unittest.TestCase):
    def test_upstream_page_assets_are_mirror_origins(self) -> None:
        origins = _mirror_origins()
        for url in UPSTREAM_PAGE_ASSETS:
            with self.subTest(url=url):
                self.assertIn(
                    urlsplit(url).hostname,
                    origins,
                    "the upstream login page and editor link their favicon on "
                    "this clearnet host; an onion vhost reaches it only through "
                    "web-svc-mirror, whose upstreams and onion rewrite come from "
                    "the role's CSP whitelist",
                )


if __name__ == "__main__":
    unittest.main()
