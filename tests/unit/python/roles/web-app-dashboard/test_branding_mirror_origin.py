from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined

from plugins.filter.mirror_filters import external_asset_origins
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.domains.default_primary import default_domain_primary
from utils.roles.mapping import ROLE_FILE_META_CSP

APPLICATION_ID = "web-app-dashboard"
CSP = PROJECT_ROOT / "roles" / APPLICATION_ID / ROLE_FILE_META_CSP
PRIMARY = default_domain_primary()
NODE_ONION = "nwfkhe2yzxbuc4q4zmqligrxngvwu6nled7lvvipoatjv2ayirm55yqd.onion"
ASSET_URL_TERMS = ("config", "web-svc-asset", "services.asset.url")


def _mirror_origins(asset_url: str) -> list[str]:
    def lookup(*terms: str) -> str:
        if terms != ASSET_URL_TERMS:
            raise AssertionError(f"img-src renders an unexpected lookup{terms}")
        return asset_url

    env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
    img_src = load_yaml_str(read_text(str(CSP)))["whitelist"]["img-src"]
    rendered = [env.from_string(token).render(lookup=lookup) for token in img_src]
    applications = {APPLICATION_ID: {"csp": {"whitelist": {"img-src": rendered}}}}
    return external_asset_origins(applications, APPLICATION_ID, PRIMARY)


class TestDashboardBrandingMirrorOrigin(unittest.TestCase):
    def test_an_external_asset_service_is_a_mirror_origin(self) -> None:
        self.assertEqual(
            _mirror_origins("https://file.infinito.nexus/assets"),
            ["file.infinito.nexus"],
            "the platform logo, favicon and company logo fall back to the asset "
            "service; when it is external, an onion dashboard reaches it only "
            "through web-svc-mirror, whose upstreams and onion rewrite come from "
            "this whitelist",
        )

    def test_a_node_served_asset_service_is_not_mirrored(self) -> None:
        for asset_url in (
            f"https://file.{PRIMARY}/assets",
            f"http://file.{NODE_ONION}/assets",
        ):
            with self.subTest(asset_url=asset_url):
                self.assertEqual(_mirror_origins(asset_url), [])


if __name__ == "__main__":
    unittest.main()
