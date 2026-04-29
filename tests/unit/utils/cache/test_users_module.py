"""Focused unit tests for ``utils.cache.users``.

Pins the public API (`get_user_defaults`, `get_merged_users`) plus the
internal helpers that only this module owns: `_load_user_defs`,
`_build_users`, `_compute_reserved_usernames`, `_load_store_users`,
`_resolve_tokens_file`, `_hydrate_users_tokens`, `_merge_users`,
`_materialize_builtin_user_aliases`. Module name is `test_users_module`
to disambiguate from the existing `tests/unit/plugins/lookup/test_users.py`
which targets the lookup plugin.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from collections import OrderedDict
from pathlib import Path

import yaml

from utils.cache import _reset_cache_for_tests
from utils.cache import base as cache_base
from utils.cache import users as cache_users


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _seed_minimal_user_role(tmp: Path, role_name: str = "web-app-foo") -> Path:
    # Per req-008 the file root of meta/users.yml IS the users map
    # (no `users:` wrapper).
    roles = tmp / "roles"
    role = roles / role_name
    _write(role / "meta" / "services.yml", "{}\n")
    _write(
        role / "meta" / "users.yml",
        f"""
        {role_name.split("-")[-1]}:
          description: "test-only user"
        """,
    )
    return roles


class TestComputeReservedUsernames(unittest.TestCase):
    def test_extracts_lowercase_alnum_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            (roles / "web-app-postgres").mkdir(parents=True)
            (roles / "web-app-mailu").mkdir(parents=True)
            (roles / "svc-db-mariadb").mkdir(parents=True)
            (roles / "not-a-role.txt").write_text("", encoding="utf-8")
            self.assertEqual(
                cache_users._compute_reserved_usernames(roles),
                ["mailu", "mariadb", "postgres"],
            )


class TestLoadUserDefs(unittest.TestCase):
    def test_aggregates_users_across_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_user_role(Path(tmp), "web-app-alpha")
            _write(
                roles / "web-app-beta" / "meta" / "users.yml",
                """
                beta:
                  description: "beta user"
                """,
            )
            defs = cache_users._load_user_defs(roles)
            self.assertIn("alpha", defs)
            self.assertIn("beta", defs)

    def test_conflicting_definitions_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp) / "roles"
            _write(
                roles / "web-app-a" / "meta" / "users.yml",
                """
                shared: {description: from-a}
                """,
            )
            _write(
                roles / "web-app-b" / "meta" / "users.yml",
                """
                shared: {description: from-b}
                """,
            )
            with self.assertRaisesRegex(ValueError, "Conflict for user 'shared'"):
                cache_users._load_user_defs(roles)


class TestBuildUsers(unittest.TestCase):
    def test_allocates_distinct_uids_for_users_without_explicit_uid(self):
        defs: OrderedDict[str, dict] = OrderedDict(
            [
                ("alice", {}),
                ("bob", {}),
            ]
        )
        users = cache_users._build_users(
            defs, primary_domain="x.example", start_id=1001, become_pwd="pw"
        )
        self.assertEqual(users["alice"]["uid"], 1001)
        self.assertEqual(users["bob"]["uid"], 1002)

    def test_explicit_uid_is_honoured(self):
        defs = OrderedDict(
            [
                ("alice", {"uid": 5000}),
                ("bob", {}),
            ]
        )
        users = cache_users._build_users(
            defs, primary_domain="x.example", start_id=1001, become_pwd="pw"
        )
        self.assertEqual(users["alice"]["uid"], 5000)
        self.assertEqual(users["bob"]["uid"], 1001)

    def test_duplicate_explicit_uid_raises(self):
        defs = OrderedDict(
            [
                ("alice", {"uid": 1500}),
                ("bob", {"uid": 1500}),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Duplicate uid 1500"):
            cache_users._build_users(
                defs, primary_domain="x.example", start_id=1001, become_pwd="pw"
            )

    def test_duplicate_username_after_overrides_raises(self):
        defs = OrderedDict(
            [
                ("alice", {"username": "shared"}),
                ("bob", {"username": "shared"}),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Duplicate username 'shared'"):
            cache_users._build_users(
                defs, primary_domain="x.example", start_id=1001, become_pwd="pw"
            )

    def test_default_email_uses_username_at_primary_domain(self):
        users = cache_users._build_users(
            OrderedDict([("alice", {})]),
            primary_domain="example.org",
            start_id=1001,
            become_pwd="pw",
        )
        self.assertEqual(users["alice"]["email"], "alice@example.org")


class TestMergeUsers(unittest.TestCase):
    def test_overrides_extend_defaults(self):
        defaults = {"alice": {"description": "from-defaults"}}
        overrides = {"alice": {"username": "alice-override"}, "bob": {}}
        merged = cache_users._merge_users(defaults, overrides)
        self.assertEqual(merged["alice"]["username"], "alice-override")
        # The defaults description survives when not overridden.
        self.assertEqual(merged["alice"]["description"], "from-defaults")
        self.assertIn("bob", merged)


class TestHydrateUsersTokens(unittest.TestCase):
    def test_store_tokens_fill_empty_in_users_only(self):
        users = {
            "alice": {"tokens": {"web-app-x": ""}},
            "bob": {"tokens": {"web-app-y": "from-user"}},
        }
        store = {
            "alice": {"tokens": {"web-app-x": "from-store"}},
            "bob": {"tokens": {"web-app-y": "store-attempt"}},
        }
        merged = cache_users._hydrate_users_tokens(users, store)
        self.assertEqual(merged["alice"]["tokens"]["web-app-x"], "from-store")
        # User-supplied non-empty token MUST win.
        self.assertEqual(merged["bob"]["tokens"]["web-app-y"], "from-user")

    def test_returns_deep_copy_independent_of_input(self):
        users = {"alice": {"tokens": {}}}
        store = {"alice": {"tokens": {"x": "y"}}}
        merged = cache_users._hydrate_users_tokens(users, store)
        merged["alice"]["tokens"]["x"] = "mutated"
        # Original `store` is untouched.
        self.assertEqual(store["alice"]["tokens"]["x"], "y")


class TestResolveTokensFile(unittest.TestCase):
    def test_falls_back_to_default_when_no_overrides(self):
        # `_resolve_tokens_file` reads `base.DEFAULT_TOKENS_FILE` at call
        # time, so a test that patches the constant takes effect on the
        # very next call.
        previous = cache_base.DEFAULT_TOKENS_FILE
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "sentinel.yml"
            sentinel.write_text("users: {}\n", encoding="utf-8")
            cache_base.DEFAULT_TOKENS_FILE = sentinel
            try:
                result = cache_users._resolve_tokens_file(variables={})
                self.assertEqual(result, sentinel)
            finally:
                cache_base.DEFAULT_TOKENS_FILE = previous

    def test_explicit_FILE_TOKENS_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "tokens.yml"
            explicit.write_text("users: {}\n", encoding="utf-8")
            result = cache_users._resolve_tokens_file(
                variables={"FILE_TOKENS": str(explicit)}
            )
            self.assertEqual(result, explicit)


class TestLoadStoreUsers(unittest.TestCase):
    def test_missing_path_returns_empty(self):
        self.assertEqual(cache_users._load_store_users(None), {})
        self.assertEqual(cache_users._load_store_users(""), {})

    def test_yaml_users_block_passes_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text(
                yaml.safe_dump({"users": {"alice": {"tokens": {"x": "y"}}}}),
                encoding="utf-8",
            )
            result = cache_users._load_store_users(path)
            self.assertEqual(result, {"alice": {"tokens": {"x": "y"}}})


class TestMaterializeBuiltinUserAliases(unittest.TestCase):
    def test_no_primary_domain_returns_users_unchanged(self):
        users = {"alice": {"username": "alice"}}
        out = cache_users._materialize_builtin_user_aliases(
            users, variables={}, templar=None
        )
        self.assertEqual(out, users)

    def test_sld_alias_username_resolved_from_DOMAIN_PRIMARY(self):
        users = {
            "sld": {"username": "{{ DOMAIN_PRIMARY.split('.') | first }}"},
        }
        out = cache_users._materialize_builtin_user_aliases(
            users,
            variables={"DOMAIN_PRIMARY": "infinito.example"},
            templar=None,
        )
        self.assertEqual(out["sld"]["username"], "infinito")


class TestGetUserDefaults(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_returns_users_per_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_user_role(Path(tmp), "web-app-foo")
            defaults = cache_users.get_user_defaults(roles_dir=roles)
            self.assertIn("foo", defaults)
            self.assertEqual(defaults["foo"]["description"], "test-only user")

    def test_caches_per_roles_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_user_role(Path(tmp), "web-app-foo")
            first = cache_users.get_user_defaults(roles_dir=roles)
            first["foo"]["mutated"] = True
            second = cache_users.get_user_defaults(roles_dir=roles)
            self.assertNotIn("mutated", second["foo"])

    def test_reserved_usernames_added_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Seed a role whose `meta/users.yml` does NOT declare the
            # role-suffix as a user. Then create an additional bare
            # role directory whose suffix MUST be auto-reserved.
            roles = _seed_minimal_user_role(Path(tmp), "web-app-foo")
            (roles / "svc-db-mariadb").mkdir(parents=True)
            defaults = cache_users.get_user_defaults(roles_dir=roles)
            self.assertIn("mariadb", defaults)
            self.assertTrue(defaults["mariadb"]["reserved"])


class TestGetMergedUsersWithOverrides(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_runtime_override_wins_for_username(self):
        with tempfile.TemporaryDirectory() as tmp:
            roles = _seed_minimal_user_role(Path(tmp), "web-app-foo")
            merged = cache_users.get_merged_users(
                variables={
                    "users": {
                        "foo": {"username": "override-user"},
                    }
                },
                roles_dir=roles,
                templar=None,
            )
            self.assertEqual(merged["foo"]["username"], "override-user")


if __name__ == "__main__":
    unittest.main()
