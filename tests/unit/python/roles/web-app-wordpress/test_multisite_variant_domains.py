"""Every WordPress variant that runs Multisite hands its child domains to the domains topic the role reads."""

from __future__ import annotations

import unittest

from plugins.filter.canonical_domains_map import FilterModule
from utils.cache.applications import get_variants

from . import PROJECT_ROOT

APPLICATION_ID = "web-app-wordpress"
PRIMARY = "main.test"


class TestMultisiteVariantDomains(unittest.TestCase):
    def test_a_multisite_variant_serves_more_than_one_canonical_domain(self):
        canonical_domains_map = FilterModule().filters()["canonical_domains_map"]
        variants = get_variants(roles_dir=PROJECT_ROOT / "roles")[APPLICATION_ID]
        multisite = {
            index: canonical_domains_map({APPLICATION_ID: variant}, PRIMARY)[
                APPLICATION_ID
            ]
            for index, variant in enumerate(variants)
            if variant["services"]["wordpress"].get("multisite", {}).get("enabled")
        }
        self.assertTrue(multisite, "no WordPress variant runs Multisite")
        for index, domains in multisite.items():
            with self.subTest(variant=index):
                self.assertGreater(len(domains), 1, domains)

    def test_variant_one_serves_the_main_blog_and_both_children(self):
        canonical_domains_map = FilterModule().filters()["canonical_domains_map"]
        variant = get_variants(roles_dir=PROJECT_ROOT / "roles")[APPLICATION_ID][1]
        self.assertEqual(
            ["blog.main.test", "biberblog.main.test", "biber.blog.main.test"],
            canonical_domains_map({APPLICATION_ID: variant}, PRIMARY)[APPLICATION_ID],
        )


if __name__ == "__main__":
    unittest.main()
