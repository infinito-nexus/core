from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache import _reset_cache_for_tests
from utils.cache.applications import get_application_defaults
from utils.cache.base import (
    PROJECT_ROOT,
    ROLES_DIR,
    _deep_merge,
    _fingerprint_mapping,
    _stable_variables_signature,
)
from utils.cache.users import (
    _build_users,
    _compute_reserved_usernames,
    _hydrate_users_tokens,
    _load_user_defs,
    _materialize_builtin_user_aliases,
    _merge_users,
    get_user_defaults,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class TestDeepMerge(unittest.TestCase):
    def test_nested_merge(self):
        base = {"a": {"b": 1, "c": 2}, "keep": [1]}
        override = {"a": {"c": 99, "d": 3}, "new": "x"}
        merged = _deep_merge(base, override)
        self.assertEqual(
            merged,
            {"a": {"b": 1, "c": 99, "d": 3}, "keep": [1], "new": "x"},
        )

    def test_scalar_override_replaces_mapping(self):
        self.assertEqual(_deep_merge({"a": 1}, "x"), "x")

    def test_override_deepcopies(self):
        base = {}
        override = {"a": {"list": [1, 2]}}
        merged = _deep_merge(base, override)
        merged["a"]["list"].append(3)
        self.assertEqual(override["a"]["list"], [1, 2])


class TestMergeUsers(unittest.TestCase):
    def test_none_overrides_returns_defaults_copy(self):
        defaults = {"alice": {"uid": 1001}}
        merged = _merge_users(defaults, None)
        self.assertEqual(merged, defaults)
        merged["alice"]["uid"] = 0
        self.assertEqual(defaults["alice"]["uid"], 1001)

    def test_override_merges_per_user(self):
        defaults = {"alice": {"uid": 1001, "email": "a@x"}}
        overrides = {"alice": {"email": "new@x"}, "bob": {"uid": 2000}}
        merged = _merge_users(defaults, overrides)
        self.assertEqual(merged["alice"], {"uid": 1001, "email": "new@x"})
        self.assertEqual(merged["bob"], {"uid": 2000})


class TestComputeReservedUsernames(unittest.TestCase):
    def test_extracts_suffix_after_last_dash(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            (roles / "web-app-mailu").mkdir()
            (roles / "svc-db-postgres").mkdir()
            (roles / "sys-ctl-alm-email").mkdir()
            (roles / "not-a-dir.txt").write_text("", encoding="utf-8")

            self.assertEqual(
                _compute_reserved_usernames(roles),
                ["email", "mailu", "postgres"],
            )

    def test_ignores_non_alnum_or_non_lower(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            (roles / "web-app-Foo").mkdir()
            (roles / "weird-name_with_underscore").mkdir()
            (roles / "svc-db-pg").mkdir()

            self.assertEqual(_compute_reserved_usernames(roles), ["pg"])


class TestFingerprintMapping(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_none_is_zero(self):
        self.assertEqual(_fingerprint_mapping(None), "0")

    def test_same_content_same_fingerprint(self):
        a = {"x": 1, "y": 2}
        b = {"y": 2, "x": 1}
        self.assertEqual(_fingerprint_mapping(a), _fingerprint_mapping(b))

    def test_different_content_different_fingerprint(self):
        a = {"x": 1}
        b = {"x": 2}
        self.assertNotEqual(_fingerprint_mapping(a), _fingerprint_mapping(b))

    def test_id_cache_short_circuits_recompute(self):
        obj = {"x": 1}
        first = _fingerprint_mapping(obj)
        obj["x"] = 999
        cached = _fingerprint_mapping(obj)
        self.assertEqual(first, cached)
        _reset_cache_for_tests()
        self.assertNotEqual(first, _fingerprint_mapping(obj))


class TestStableVariablesSignature(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_empty_variables_returns_sentinel(self):
        self.assertEqual(_stable_variables_signature(None), ("0", "0", "", ""))
        self.assertEqual(_stable_variables_signature({}), ("0", "0", "", ""))

    def test_captures_key_subset(self):
        sig = _stable_variables_signature(
            {
                "applications": {"a": 1},
                "users": {"u": 2},
                "DOMAIN_PRIMARY": "example.com",
                "SYSTEM_EMAIL_DOMAIN": "mail.example.com",
                "irrelevant": "noise",
            }
        )
        self.assertEqual(sig[2], "example.com")
        self.assertEqual(sig[3], "mail.example.com")
        self.assertNotEqual(sig[0], "0")
        self.assertNotEqual(sig[1], "0")

    def test_signature_stable_across_identical_content(self):
        v1 = {"applications": {"a": 1}, "users": {"u": 2}}
        v2 = {"applications": {"a": 1}, "users": {"u": 2}}
        self.assertEqual(
            _stable_variables_signature(v1), _stable_variables_signature(v2)
        )


class TestLoadUserDefs(unittest.TestCase):
    def test_merges_non_conflicting_across_roles(self):
        # Per req-008 the file root of meta/users.yml IS the users map
        # (no `users:` wrapper).
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "role-a/meta/users.yml",
                """
                alice:
                  username: alice
                """,
            )
            _write(
                roles / "role-b/meta/users.yml",
                """
                alice:
                  email: alice@x
                bob:
                  username: bob
                """,
            )
            defs = _load_user_defs(roles)
            self.assertEqual(defs["alice"], {"username": "alice", "email": "alice@x"})
            self.assertEqual(defs["bob"], {"username": "bob"})

    def test_conflicting_field_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "role-a/meta/users.yml",
                """
                alice:
                  uid: 1001
                """,
            )
            _write(
                roles / "role-b/meta/users.yml",
                """
                alice:
                  uid: 2002
                """,
            )
            with self.assertRaisesRegex(ValueError, "Conflict for user 'alice'"):
                _load_user_defs(roles)

    def test_non_dict_user_entry_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "role-a/meta/users.yml",
                """
                alice: "not-a-dict"
                """,
            )
            with self.assertRaisesRegex(ValueError, "Invalid definition"):
                _load_user_defs(roles)


class TestBuildUsers(unittest.TestCase):
    def _defs(self, mapping):
        from collections import OrderedDict

        return OrderedDict(mapping)

    def test_allocates_uids_starting_at_start_id(self):
        defs = self._defs([("alice", {}), ("bob", {})])
        users = _build_users(defs, "example.com", start_id=1001, become_pwd="pw")
        self.assertEqual(users["alice"]["uid"], 1001)
        self.assertEqual(users["bob"]["uid"], 1002)
        self.assertEqual(users["alice"]["gid"], 1001)

    def test_explicit_uid_preserved_allocator_skips(self):
        defs = self._defs(
            [("alice", {"uid": 1001}), ("bob", {}), ("carol", {"uid": 1002})]
        )
        users = _build_users(defs, "example.com", start_id=1001, become_pwd="pw")
        self.assertEqual(users["alice"]["uid"], 1001)
        self.assertEqual(users["bob"]["uid"], 1003)
        self.assertEqual(users["carol"]["uid"], 1002)

    def test_duplicate_explicit_uid_raises(self):
        defs = self._defs([("alice", {"uid": 1001}), ("bob", {"uid": 1001})])
        with self.assertRaisesRegex(ValueError, "Duplicate uid 1001"):
            _build_users(defs, "example.com", start_id=1001, become_pwd="pw")

    def test_duplicate_username_raises(self):
        defs = self._defs(
            [("alice", {"username": "shared"}), ("bob", {"username": "shared"})]
        )
        with self.assertRaisesRegex(ValueError, "Duplicate username 'shared'"):
            _build_users(defs, "example.com", start_id=1001, become_pwd="pw")

    def test_duplicate_email_raises(self):
        defs = self._defs(
            [
                ("alice", {"email": "same@x"}),
                ("bob", {"email": "same@x"}),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Duplicate email 'same@x'"):
            _build_users(defs, "example.com", start_id=1001, become_pwd="pw")

    def test_defaults_fill_missing_fields(self):
        defs = self._defs([("alice", {})])
        users = _build_users(defs, "example.com", start_id=1001, become_pwd="pw")
        self.assertEqual(users["alice"]["username"], "alice")
        self.assertEqual(users["alice"]["email"], "alice@example.com")
        self.assertEqual(users["alice"]["password"], "pw")
        self.assertEqual(users["alice"]["firstname"], "alice")
        self.assertEqual(users["alice"]["lastname"], "example.com")


class TestHydrateUsersTokens(unittest.TestCase):
    def test_fills_only_missing_tokens(self):
        users = {
            "alice": {"tokens": {"app-a": "keep", "app-b": ""}},
            "bob": {"tokens": {}},
        }
        store = {
            "alice": {"tokens": {"app-a": "overwrite-attempt", "app-b": "fill"}},
            "bob": {"tokens": {"app-c": "fresh"}},
            "carol": {"tokens": {"app-d": "orphan"}},
        }
        hydrated = _hydrate_users_tokens(users, store)
        self.assertEqual(hydrated["alice"]["tokens"]["app-a"], "keep")
        self.assertEqual(hydrated["alice"]["tokens"]["app-b"], "fill")
        self.assertEqual(hydrated["bob"]["tokens"]["app-c"], "fresh")
        self.assertIn("carol", hydrated)
        self.assertEqual(hydrated["carol"]["tokens"]["app-d"], "orphan")

    def test_empty_store_is_passthrough(self):
        users = {"alice": {"tokens": {"a": "1"}}}
        self.assertEqual(_hydrate_users_tokens(users, None), users)
        self.assertEqual(_hydrate_users_tokens(users, {}), users)

    def test_does_not_mutate_input(self):
        users = {"alice": {"tokens": {}}}
        store = {"alice": {"tokens": {"x": "y"}}}
        _hydrate_users_tokens(users, store)
        self.assertEqual(users["alice"]["tokens"], {})


class TestMaterializeBuiltinUserAliases(unittest.TestCase):
    def test_rewrites_sld_and_tld_usernames(self):
        users = {
            "sld": {"username": "{{ DOMAIN_PRIMARY.split('.')[0] }}"},
            "tld": {"username": "{{ DOMAIN_PRIMARY.split('.')[1] }}"},
        }
        result = _materialize_builtin_user_aliases(
            users, {"DOMAIN_PRIMARY": "example.com"}
        )
        self.assertEqual(result["sld"]["username"], "example")
        self.assertEqual(result["tld"]["username"], "com")

    def test_no_domain_primary_is_passthrough(self):
        users = {"sld": {"username": "{{ DOMAIN_PRIMARY.split('.')[0] }}"}}
        result = _materialize_builtin_user_aliases(users, {})
        self.assertEqual(result, users)

    def test_non_placeholder_username_untouched(self):
        users = {"sld": {"username": "literal"}}
        result = _materialize_builtin_user_aliases(
            users, {"DOMAIN_PRIMARY": "example.com"}
        )
        self.assertEqual(result["sld"]["username"], "literal")


class TestGetApplicationDefaults(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def tearDown(self) -> None:
        _reset_cache_for_tests()

    def test_reads_role_config_files(self):
        # Per req-008 the server topic now lives in its own
        # `meta/server.yml`, not nested inside `meta/services.yml`.
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "web-app-alpha/meta/server.yml",
                """
                domains:
                  canonical:
                    - alpha.example
                """,
            )
            _write(
                roles / "web-app-beta/meta/server.yml",
                """
                domains:
                  canonical:
                    - beta.example
                """,
            )
            defaults = get_application_defaults(roles_dir=roles)
            self.assertEqual(sorted(defaults.keys()), ["web-app-alpha", "web-app-beta"])
            self.assertIn("group_id", defaults["web-app-alpha"])
            self.assertEqual(
                defaults["web-app-alpha"]["server"]["domains"]["canonical"],
                ["alpha.example"],
            )

    def test_wires_users_to_lookup_indirection(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "web-app-alpha/meta/server.yml",
                """
                {}
                """,
            )
            _write(
                roles / "web-app-alpha/meta/users.yml",
                """
                administrator:
                  username: administrator
                """,
            )
            defaults = get_application_defaults(roles_dir=roles)
            self.assertEqual(
                defaults["web-app-alpha"]["users"]["administrator"],
                "{{ lookup('users', 'administrator') }}",
            )

    def test_cache_returns_deep_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "web-app-alpha/meta/server.yml",
                """
                domains:
                  canonical:
                    - alpha.example
                """,
            )
            first = get_application_defaults(roles_dir=roles)
            first["web-app-alpha"]["server"]["mutated"] = True
            second = get_application_defaults(roles_dir=roles)
            self.assertNotIn("mutated", second["web-app-alpha"]["server"])


class TestGetUserDefaults(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def tearDown(self) -> None:
        _reset_cache_for_tests()

    def test_includes_role_defined_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "web-app-alpha/meta/users.yml",
                """
                administrator:
                  username: administrator
                """,
            )
            users = get_user_defaults(roles_dir=roles)
            self.assertIn("administrator", users)
            self.assertEqual(users["administrator"]["uid"], 1001)

    def test_adds_reserved_users_from_role_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            (roles / "svc-db-postgres").mkdir()
            (roles / "sys-ctl-alm-email").mkdir()
            users = get_user_defaults(roles_dir=roles)
            self.assertIn("postgres", users)
            self.assertTrue(users["postgres"]["reserved"])
            self.assertIn("email", users)
            self.assertTrue(users["email"]["reserved"])

    def test_cache_returns_deep_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            _write(
                roles / "web-app-alpha/meta/users.yml",
                """
                administrator:
                  username: administrator
                """,
            )
            first = get_user_defaults(roles_dir=roles)
            first["administrator"]["mutated"] = True
            second = get_user_defaults(roles_dir=roles)
            self.assertNotIn("mutated", second["administrator"])


class TestImplicitRolesDir(unittest.TestCase):
    """Pin the implicit ROLES_DIR to the actual repo `roles/` directory.

    Why pin: when this module was at `utils/runtime_data.py`,
    `parents[1]` resolved to the repo root. After the move to
    `utils/cache/base.py` (and previously `utils/cache/data.py`),
    `parents[1]` silently became `utils/`, which is itself a python
    package. Glob walks like
    `<utils>/roles/*/meta/users.yml` then yielded zero matches and
    `lookup('users', 'contact')` started failing during deploy as if
    `contact` were undefined. Encode the invariant explicitly so any
    future move that changes the depth is caught here, not by a
    multi-hour deploy that fails inside Ansible.
    """

    def test_project_root_is_repo_root(self):
        # The repo root has both `roles/` and `cli/` at the top level;
        # `utils/` does not. Asserting both keeps the test robust against
        # accidental drift to either direction.
        self.assertTrue(
            (PROJECT_ROOT / "roles").is_dir(),
            f"expected <repo>/roles under PROJECT_ROOT={PROJECT_ROOT}",
        )
        self.assertTrue(
            (PROJECT_ROOT / "cli").is_dir(),
            f"expected <repo>/cli under PROJECT_ROOT={PROJECT_ROOT}",
        )
        self.assertEqual(ROLES_DIR, PROJECT_ROOT / "roles")

    def test_implicit_user_defaults_include_role_defined_users(self):
        # `contact` is contributed by web-app-odoo and web-app-espocrm
        # role users files. If ROLES_DIR is wrong, the implicit lookup
        # silently returns an empty defaults map and this regresses.
        defaults = get_user_defaults()
        self.assertIn("contact", defaults)


def _run_in_ansible_blocked_subprocess(snippet: str):
    """Spawn a fresh `python3` subprocess that installs a meta-path
    finder denying every `ansible*` import, then runs the given
    snippet against the real repo. Returns ``(returncode, stdout,
    stderr)``.

    Subprocess isolation avoids the in-process module-state hazards
    (namespace packages, cross-test sys.modules churn, identity
    fragmentation of cache dicts) that plagued earlier in-process
    `_AnsibleBlock` shims and broke under Python 3.13 inside the
    infinito container. Each subprocess starts with a clean import
    state and a clean `sys.meta_path`.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[4]
    preamble = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "class _Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name == 'ansible' or name.startswith('ansible.'):\n"
        "            raise ImportError(f'blocked: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Block())\n"
    ) % str(repo_root)
    code = preamble + snippet
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


class TestImportableWithoutAnsible(unittest.TestCase):
    """Pin: `utils.cache.applications` MUST be importable AND its
    hot-path callables MUST run without `ansible` on sys.path.

    Why pin: the `cli.deploy.development` CLI runs on the GitHub Actions
    runner host (see scripts/tests/deploy/ci/dedicated.sh) where the
    runner Python has no `ansible` package. The original CI failure
    (run 24934007615) was at *import* time. The follow-up CI failure
    (run 24935979190) showed that import-only guards are not enough:
    `_build_variants` still instantiated `ApplicationGidLookup` at
    *call* time, which transitively imported
    `ansible.plugins.lookup.LookupBase` the moment the function was
    invoked. The fix split `compute_application_gid` (pure-Python) from
    the ansible-facing `LookupModule` wrapper. These tests pin BOTH
    layers — import-time AND call-time — by spawning a fresh subprocess
    so the regression is caught at unit-test time, not by a multi-hour
    CI matrix.
    """

    def test_get_variants_importable_without_ansible(self):
        rc, out, err = _run_in_ansible_blocked_subprocess(
            "from utils.cache.applications import get_variants\n"
            "assert callable(get_variants)\n"
            "print('OK')\n"
        )
        self.assertEqual(rc, 0, msg=f"stderr=\n{err}\nstdout=\n{out}")
        self.assertIn("OK", out)

    def test_inventory_module_importable_without_ansible(self):
        # The actual call chain that broke in CI run 24934007615:
        #   cli.deploy.development.init -> .inventory ->
        #   utils.cache.applications
        rc, out, err = _run_in_ansible_blocked_subprocess(
            "from cli.deploy.development.inventory import "
            "plan_dev_inventory_matrix\n"
            "assert callable(plan_dev_inventory_matrix)\n"
            "print('OK')\n"
        )
        self.assertEqual(rc, 0, msg=f"stderr=\n{err}\nstdout=\n{out}")
        self.assertIn("OK", out)

    def test_get_variants_callable_without_ansible(self):
        # Pins CI run 24935979190 specifically: the import-time guards
        # added in 8e4886d70 passed this very file's import-only tests
        # but `get_variants(roles_dir=...)` still triggered the lazy
        # import of `ApplicationGidLookup` and died at call time. This
        # test invokes the function AGAINST the real repo roles dir
        # while ansible is blocked.
        rc, out, err = _run_in_ansible_blocked_subprocess(
            "from utils.cache.applications import get_variants\n"
            "from utils.cache.base import ROLES_DIR\n"
            "v = get_variants(roles_dir=ROLES_DIR)\n"
            "assert isinstance(v, dict)\n"
            "assert len(v) > 0, 'expected at least one role'\n"
            "sample_app, sample_variants = next(iter(v.items()))\n"
            "assert isinstance(sample_variants, list)\n"
            "assert len(sample_variants) > 0\n"
            "print('OK', len(v))\n"
        )
        self.assertEqual(rc, 0, msg=f"stderr=\n{err}\nstdout=\n{out}")
        self.assertIn("OK", out)

    def test_plan_dev_inventory_matrix_callable_without_ansible(self):
        # Same exhaustive shape as above, one level higher: the actual
        # CLI path is `cli.deploy.development.init.handler` ->
        # `plan_dev_inventory_matrix(...)` -> `get_variants(...)`. We
        # invoke the planner so a future regression at any layer of
        # this chain trips here.
        rc, out, err = _run_in_ansible_blocked_subprocess(
            "from cli.deploy.development.inventory import "
            "plan_dev_inventory_matrix\n"
            "from utils.cache.applications import get_variants\n"
            "from utils.cache.base import ROLES_DIR\n"
            "apps = list(get_variants(roles_dir=ROLES_DIR).keys())\n"
            "sample = [apps[0]]\n"
            "plan = plan_dev_inventory_matrix(\n"
            "    roles_dir=str(ROLES_DIR),\n"
            "    primary_apps=sample,\n"
            "    base_inventory_dir='/tmp/_inv_unused',\n"
            ")\n"
            "assert len(plan) > 0\n"
            "round_index, inv_dir, round_variants, include_R = plan[0]\n"
            "assert round_index == 0\n"
            "assert sample[0] in round_variants\n"
            "assert sample[0] in include_R\n"
            "print('OK')\n"
        )
        self.assertEqual(rc, 0, msg=f"stderr=\n{err}\nstdout=\n{out}")
        self.assertIn("OK", out)


if __name__ == "__main__":
    unittest.main()
