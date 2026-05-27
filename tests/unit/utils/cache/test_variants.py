"""Unit tests for the per-role `meta/variants.yml` matrix-deploy
loader (`utils.cache.applications.get_variants`) and the variant-free
base-config default that `get_merged_applications` falls back on when
no inventory-level `applications.<app>` override is set."""

import os
import sys
import textwrap
import unittest
from pathlib import Path

from . import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.cache import _reset_cache_for_tests
from utils.cache.applications import (
    _build_variants,
    get_application_defaults,
    get_merged_applications,
    get_variants,
)
from utils.cache.applications import (
    _load_variants_overrides as _load_yaml_variant_list,
)
from utils.roles.mapping import (
    ROLE_FILE_META_SERVER,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
)


def _write_role(
    roles_dir: Path,
    name: str,
    *,
    config: str | None = None,
    meta: str | None = None,
    server: str | None = None,
) -> None:
    """Write a synthetic role tree under <roles_dir>/<name>/meta/.

    ``config``  -> meta/services.yml content (the file root IS the services
                   map)
    ``server``  -> meta/server.yml content
    ``meta``    -> meta/variants.yml content (matrix-deploy variant list)
    """
    role = roles_dir / name
    (role / "meta").mkdir(parents=True, exist_ok=True)
    if config is not None:
        (role / ROLE_FILE_META_SERVICES).write_text(textwrap.dedent(config))
    if server is not None:
        (role / ROLE_FILE_META_SERVER).write_text(textwrap.dedent(server))
    if meta is not None:
        (role / ROLE_FILE_META_VARIANTS).write_text(textwrap.dedent(meta))


class TestLoadYamlVariantList(unittest.TestCase):
    def test_missing_file_yields_single_empty_variant(self):
        self.assertEqual(_load_yaml_variant_list(Path("/nonexistent")), [{}])

    def test_empty_file_yields_single_empty_variant(self):
        path = Path(self._write_tmp(""))
        self.assertEqual(_load_yaml_variant_list(path), [{}])

    def test_empty_list_yields_single_empty_variant(self):
        path = Path(self._write_tmp("[]\n"))
        self.assertEqual(_load_yaml_variant_list(path), [{}])

    def test_null_entry_normalised_to_empty_dict(self):
        path = Path(self._write_tmp("- null\n- {a: 1}\n"))
        self.assertEqual(_load_yaml_variant_list(path), [{}, {"a": 1}])

    def test_non_list_root_rejected(self):
        path = Path(self._write_tmp("a: 1\n"))
        with self.assertRaises(TypeError):
            _load_yaml_variant_list(path)

    def test_non_mapping_entry_rejected(self):
        path = Path(self._write_tmp("- 42\n"))
        with self.assertRaises(ValueError):
            _load_yaml_variant_list(path)

    def _write_tmp(self, content: str) -> str:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as f:
            f.write(content)
        self.addCleanup(os.remove, f.name)
        return f.name


class TestApplicationVariants(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="variants-")
        self.roles_dir = Path(self.tmp)
        _reset_cache_for_tests()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_cache_for_tests()

    def test_role_without_meta_yields_single_variant(self):
        _write_role(self.roles_dir, "web-app-foo", config="foo:\n  hello: world\n")
        variants = _build_variants(self.roles_dir)
        self.assertEqual(list(variants.keys()), ["web-app-foo"])
        self.assertEqual(len(variants["web-app-foo"]), 1)
        self.assertEqual(
            variants["web-app-foo"][0]["services"]["foo"]["hello"], "world"
        )

    def test_role_with_two_variants_deep_merges_each_entry(self):
        # Per, the role's meta is split: server -> meta/server.yml,
        # services -> meta/services.yml. The variants file overrides the
        # assembled payload (top-level keys: server, services, ...).
        role = self.roles_dir / "web-app-bar"
        (role / "meta").mkdir(parents=True, exist_ok=True)
        (role / ROLE_FILE_META_SERVICES).write_text(
            textwrap.dedent(
                """
                bar:
                  enabled: false
                """
            )
        )
        (role / ROLE_FILE_META_SERVER).write_text(
            textwrap.dedent(
                """
                domains:
                  canonical: ["bar.example"]
                """
            )
        )
        (role / ROLE_FILE_META_VARIANTS).write_text(
            textwrap.dedent(
                """
                - {}
                - services:
                    bar:
                      enabled: true
                  server:
                    domains:
                      canonical: ["bar.example", "shop.bar.example"]
                """
            )
        )
        variants = _build_variants(self.roles_dir)["web-app-bar"]
        self.assertEqual(len(variants), 2)
        self.assertEqual(variants[0]["services"]["bar"]["enabled"], False)
        self.assertEqual(variants[0]["server"]["domains"]["canonical"], ["bar.example"])
        self.assertEqual(variants[1]["services"]["bar"]["enabled"], True)
        self.assertEqual(
            variants[1]["server"]["domains"]["canonical"],
            ["bar.example", "shop.bar.example"],
        )

    def test_get_application_defaults_returns_variant_free_base_config(self):
        _write_role(
            self.roles_dir,
            "web-app-baz",
            config="baz:\n  value: 1\n",
            meta=textwrap.dedent(
                """
                - {}
                - services:
                    baz:
                      value: 2
                """
            ),
        )
        defaults = get_application_defaults(roles_dir=self.roles_dir)
        self.assertEqual(defaults["web-app-baz"]["services"]["baz"]["value"], 1)

    def test_get_application_defaults_omits_variant_zero_only_keys(self):
        """Defaults MUST come from the variant-free base config, not
        variant 0. Otherwise a service key that only variant 0 enables
        (and that variant N intentionally omits) leaks into variant N's
        runtime view via deep-merge in `get_merged_applications`."""
        _write_role(
            self.roles_dir,
            "web-app-leak",
            config="alpha:\n  enabled: false\n",
            meta=textwrap.dedent(
                """
                - services:
                    alpha:
                      enabled: true
                      shared: true
                - services:
                    beta:
                      enabled: true
                      shared: true
                """
            ),
        )
        defaults = get_application_defaults(roles_dir=self.roles_dir)
        alpha = defaults["web-app-leak"]["services"]["alpha"]
        self.assertEqual(alpha.get("enabled"), False)
        self.assertNotIn("beta", defaults["web-app-leak"]["services"])

    def test_get_variants_caches_per_roles_dir(self):
        _write_role(self.roles_dir, "web-app-cache", config="cache:\n  x: 1\n")
        first = get_variants(roles_dir=self.roles_dir)
        second = get_variants(roles_dir=self.roles_dir)
        self.assertEqual(first, second)
        # Mutating the returned copy MUST NOT corrupt the cache.
        second["web-app-cache"][0]["services"]["cache"]["x"] = 999
        self.assertEqual(
            get_variants(roles_dir=self.roles_dir)["web-app-cache"][0]["services"][
                "cache"
            ]["x"],
            1,
        )


class TestMergedApplicationsUsesBaseConfig(unittest.TestCase):
    """The runtime loader reads no active-variant selector. Variant N
    data is baked into the inventory by
    `cli.administration.deploy.development.inventory.build_dev_inventory` at init time
    and reaches the merged payload as an `applications.<app>` override.
    The loader's defaults are the role's variant-free base config so
    no variant's service flags leak into another variant's runtime view
    via deep-merge; inventory-level overrides remain authoritative."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp(prefix="variants-merged-")
        self.roles_dir = Path(self.tmp)
        _reset_cache_for_tests()
        _write_role(
            self.roles_dir,
            "web-app-multi",
            server=textwrap.dedent(
                """
                domains:
                  canonical: ["multi.example"]
                """
            ),
            meta=textwrap.dedent(
                """
                - {}
                - server:
                    domains:
                      canonical:
                        - "blog.multi.example"
                        - "shop.multi.example"
                """
            ),
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_cache_for_tests()

    def test_no_inventory_overrides_yield_base_config(self):
        merged = get_merged_applications(
            variables={},
            roles_dir=str(self.roles_dir),
        )
        self.assertEqual(
            merged["web-app-multi"]["server"]["domains"]["canonical"],
            ["multi.example"],
        )

    def test_inventory_override_swaps_in_variant_one_payload(self):
        # This mirrors what the init step bakes into host_vars when
        # round 1 selects variant 1 for `web-app-multi`. Override wins
        # via deep merge.
        variant_one = {
            "server": {
                "domains": {
                    "canonical": ["blog.multi.example", "shop.multi.example"],
                },
            },
        }
        merged = get_merged_applications(
            variables={"applications": {"web-app-multi": variant_one}},
            roles_dir=str(self.roles_dir),
        )
        self.assertEqual(
            merged["web-app-multi"]["server"]["domains"]["canonical"],
            ["blog.multi.example", "shop.multi.example"],
        )

    def test_active_variants_marker_is_ignored_by_loader(self):
        # The previous `_active_variants` runtime selector has been
        # retired; the loader MUST NOT honour it any more. This test
        # guards against accidentally re-introducing the runtime path.
        merged = get_merged_applications(
            variables={"_active_variants": {"web-app-multi": 1}},
            roles_dir=str(self.roles_dir),
        )
        self.assertEqual(
            merged["web-app-multi"]["server"]["domains"]["canonical"],
            ["multi.example"],
        )


if __name__ == "__main__":
    unittest.main()
