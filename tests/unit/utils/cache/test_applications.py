"""Focused unit tests for ``utils.cache.applications``.

Pins the public API (`get_application_defaults`, `get_variants`,
`get_merged_applications`) plus the cache invariants (per-roles_dir
keying, deep-copy on read), and the strict ansible-free import-time
contract that the GitHub Actions runner-host CLI path depends on.

The matrix-deploy variants loader is exhaustively covered in
test_variants.py; this file owns the module-API contract.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache import _reset_cache_for_tests
from utils.cache import applications as cache_apps
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
    ROLE_FILE_META_VARIANTS,
)

from . import PROJECT_ROOT


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _seed_minimal_roles(tmp: Path) -> Path:
    """Create a minimal `<tmp>/roles/web-app-foo/meta/...` tree
    so applications/variants can resolve a real role.
    """
    roles = tmp / "roles"
    role = roles / "web-app-foo"
    _write(
        role / ROLE_FILE_META_SERVICES,
        """
        foo:
          image: foo
          version: latest
        """,
    )
    _write(
        role / ROLE_FILE_META_USERS,
        """
        administrator: {}
        """,
    )
    return roles


class TestGetApplicationDefaults(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_returns_dict_per_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            defaults = cache_apps.get_application_defaults(roles_dir=roles)
            self.assertIn("web-app-foo", defaults)
            self.assertIn("services", defaults["web-app-foo"])

    def test_caches_per_roles_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            first = cache_apps.get_application_defaults(roles_dir=roles)
            # Mutate the returned copy; the cache MUST hand back a fresh
            # deep copy on the next call.
            first["web-app-foo"]["mutated"] = True
            second = cache_apps.get_application_defaults(roles_dir=roles)
            self.assertNotIn("mutated", second["web-app-foo"])

    def test_users_block_rewritten_to_lookup_jinja(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            defaults = cache_apps.get_application_defaults(roles_dir=roles)
            users = defaults["web-app-foo"]["users"]
            self.assertEqual(
                users["administrator"],
                "{{ lookup('users', 'administrator') }}",
            )


class TestGetVariants(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_returns_single_variant_when_no_meta_variants_yml(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            variants = cache_apps.get_variants(roles_dir=roles)
            self.assertEqual(len(variants["web-app-foo"]), 1)

    def test_returns_multiple_variants_when_meta_variants_yml_lists_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            _write(
                roles / "web-app-foo" / ROLE_FILE_META_VARIANTS,
                """
                - {}
                - services:
                    foo:
                      image: foo-alt
                """,
            )
            variants = cache_apps.get_variants(roles_dir=roles)
            self.assertEqual(len(variants["web-app-foo"]), 2)
            # Variant 0 (default) keeps the canonical image; variant 1 has the
            # override applied.
            self.assertEqual(
                variants["web-app-foo"][0]["services"]["foo"]["image"],
                "foo",
            )
            self.assertEqual(
                variants["web-app-foo"][1]["services"]["foo"]["image"],
                "foo-alt",
            )

    def test_caches_per_roles_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            first = cache_apps.get_variants(roles_dir=roles)
            first["web-app-foo"][0]["mutated"] = True
            second = cache_apps.get_variants(roles_dir=roles)
            self.assertNotIn("mutated", second["web-app-foo"][0])


class TestGetVariantOverridesOnly(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_returns_single_empty_override_when_no_meta_variants_yml(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            overrides = cache_apps.get_variant_overrides_only(roles_dir=roles)
            self.assertEqual(overrides["web-app-foo"], [{}])

    def test_returns_raw_overrides_without_base_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            _write(
                roles / "web-app-foo" / ROLE_FILE_META_VARIANTS,
                """
                - {}
                - services:
                    foo:
                      image: foo-alt
                """,
            )
            overrides = cache_apps.get_variant_overrides_only(roles_dir=roles)
            # Variant 0 stays empty (no override) — the role's
            # `meta/services.yml` baseline (image=foo) is NOT mixed in.
            self.assertEqual(overrides["web-app-foo"][0], {})
            # Variant 1 carries only the override fields.
            self.assertEqual(
                overrides["web-app-foo"][1],
                {"services": {"foo": {"image": "foo-alt"}}},
            )

    def test_caches_per_roles_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            first = cache_apps.get_variant_overrides_only(roles_dir=roles)
            first["web-app-foo"][0]["mutated"] = True
            second = cache_apps.get_variant_overrides_only(roles_dir=roles)
            self.assertNotIn("mutated", second["web-app-foo"][0])


class TestBuildRoleBaseConfig(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_empty_meta_yields_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / "roles" / "web-app-empty"
            (role / "meta").mkdir(parents=True)
            self.assertEqual(
                cache_apps._build_role_base_config(role, role.parent),
                {},
            )


class TestGetMergedApplicationsRespectsOverrides(unittest.TestCase):
    """Smoke test that `get_merged_applications` deep-merges runtime
    `applications` overrides on top of the role defaults. The full
    rendering pipeline (with templar) is covered in test_data.py and
    integration suites; this file pins the contract from the
    applications module's perspective.
    """

    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_runtime_override_wins_over_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_roles(Path(tmp))
            merged = cache_apps.get_merged_applications(
                variables={
                    "applications": {
                        "web-app-foo": {
                            "services": {"foo": {"image": "override"}},
                        }
                    }
                },
                roles_dir=roles,
                templar=None,
            )
            self.assertEqual(
                merged["web-app-foo"]["services"]["foo"]["image"],
                "override",
            )


class TestApplicationsImportableWithoutAnsible(unittest.TestCase):
    """The CI runner-host CLI path
    (`cli.administration.deploy.development.init` -> `plan_dev_inventory_matrix` ->
    `get_variants`) MUST stay ansible-free. CI run 24935979190 broke
    because `_build_variants` instantiated `ApplicationGidLookup`,
    pulling `ansible.plugins.lookup.LookupBase` at call time. This
    test pins both the import-time AND call-time invariants by
    spawning a fresh subprocess so namespace-package / sys.modules
    state cannot leak across tests.
    """

    def test_module_imports_and_get_variants_callable_without_ansible(self):
        import subprocess

        repo_root = PROJECT_ROOT
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(repo_root)!r})\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'ansible' or name.startswith('ansible.'):\n"
            "            raise ImportError(f'blocked: {name}')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "from utils.cache.applications import get_variants\n"
            "assert callable(get_variants)\n"
            "from utils.cache.base import ROLES_DIR\n"
            "v = get_variants(roles_dir=ROLES_DIR)\n"
            "assert len(v) > 0\n"
            "print('OK', len(v))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=60,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stderr=\n{result.stderr}\nstdout=\n{result.stdout}",
        )
        self.assertIn("OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
