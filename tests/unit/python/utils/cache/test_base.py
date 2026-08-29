"""Focused unit tests for ``utils.cache.base``.

Covers the cross-cutting helpers in isolation: constants, deep_merge,
yaml-loaders, signatures, content fingerprints, _reset(), and the
templar-render machinery (with both no-templar and stub-templar
inputs). The broader integration of these helpers via the
applications/users/domains paths is covered in the per-domain test
files; this file pins the contract of base itself.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache import _reset_cache_for_tests, base
from utils.paths import FILE_TOKENS


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class TestProjectRootInvariants(unittest.TestCase):
    """`base.PROJECT_ROOT` must point at the actual repo root, not at
    `<repo>/utils/`. CI run 24934007615 was caused by exactly this
    drift after `utils/cache/data.py` was moved one level deeper.
    """

    def test_project_root_resolves_to_repo_root(self):
        self.assertTrue((base.PROJECT_ROOT / "roles").is_dir())
        self.assertTrue((base.PROJECT_ROOT / "cli").is_dir())
        self.assertEqual(base.ROLES_DIR, base.PROJECT_ROOT / "roles")

    def test_default_tokens_file_is_secrets_yaml(self):
        self.assertEqual(base.DEFAULT_TOKENS_FILE, FILE_TOKENS)


class TestDeepMerge(unittest.TestCase):
    def test_overrides_win_on_scalar_keys(self):
        result = base._deep_merge({"a": 1, "b": 2}, {"b": 99})
        self.assertEqual(result, {"a": 1, "b": 99})

    def test_recurses_into_nested_mappings(self):
        result = base._deep_merge(
            {"x": {"y": 1, "z": 2}},
            {"x": {"y": 99}},
        )
        self.assertEqual(result, {"x": {"y": 99, "z": 2}})

    def test_override_replaces_when_types_differ(self):
        result = base._deep_merge({"x": {"y": 1}}, {"x": ["a", "b"]})
        self.assertEqual(result, {"x": ["a", "b"]})

    def test_returns_deep_copy_of_override_when_base_is_none(self):
        override = {"x": [1, 2, 3]}
        result = base._deep_merge(None, override)
        self.assertEqual(result, override)
        result["x"].append(4)
        self.assertEqual(override["x"], [1, 2, 3])


class TestResolveRolesDir(unittest.TestCase):
    def test_explicit_arg_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                base._resolve_roles_dir(roles_dir=tmp), Path(tmp).resolve()
            )

    def test_falls_back_to_module_default(self):
        self.assertEqual(base._resolve_roles_dir(), base.ROLES_DIR.resolve())


class TestCacheKey(unittest.TestCase):
    def test_returns_resolved_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(base._cache_key(Path(tmp)), str(Path(tmp).resolve()))


class TestFingerprintMapping(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_none_short_circuits_to_zero(self):
        self.assertEqual(base._fingerprint_mapping(None), "0")

    def test_same_object_hashes_stably(self):
        obj = {"a": 1}
        first = base._fingerprint_mapping(obj)
        self.assertEqual(first, base._fingerprint_mapping(obj))

    def test_in_place_mutation_changes_the_digest(self):
        obj = {"a": 1}
        first = base._fingerprint_mapping(obj)
        obj["a"] = 2
        self.assertNotEqual(first, base._fingerprint_mapping(obj))

    def test_equal_content_distinct_objects_hash_to_same_digest(self):
        a = {"a": 1, "b": 2}
        b = {"b": 2, "a": 1}
        self.assertEqual(base._fingerprint_mapping(a), base._fingerprint_mapping(b))


class TestStableVariablesSignature(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_empty_variables_collapses_to_canonical_tuple(self):
        self.assertEqual(
            base._stable_variables_signature(None),
            ("0", "0", "", ""),
        )
        self.assertEqual(
            base._stable_variables_signature({}),
            ("0", "0", "", ""),
        )

    def test_includes_domain_primary_and_email_domain_strings(self):
        sig = base._stable_variables_signature(
            {
                "applications": {"web-app-x": {}},
                "DOMAIN_PRIMARY": "infinito.example",
                "SYSTEM_EMAIL_DOMAIN": "mail.infinito.example",
            }
        )
        self.assertEqual(sig[2], "infinito.example")
        self.assertEqual(sig[3], "mail.infinito.example")


class TestTokensFileSignature(unittest.TestCase):
    def test_missing_file_returns_zeroed_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            sig = base._tokens_file_signature(Path(tmp) / "absent.yml")
            self.assertEqual(sig[1], 0)
            self.assertEqual(sig[2], 0)

    def test_signature_changes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text("a: 1\n", encoding="utf-8")
            sig_before = base._tokens_file_signature(path)
            path.write_text("a: 1\nb: 2\n", encoding="utf-8")
            sig_after = base._tokens_file_signature(path)
            self.assertNotEqual(sig_before, sig_after)


class TestRenderWithTemplar(unittest.TestCase):
    """`_render_with_templar` is the single ansible-coupled symbol in
    base. We don't simulate a real Templar (that's covered by the
    domain integration tests); we pin the no-templar short-circuit and
    the basic stub-templar dispatch shape so a regression in the
    closure setup or available_variables push/pop trips here.
    """

    def test_returns_value_unchanged_when_templar_is_none(self):
        sentinel = {"a": 1, "b": [2, 3]}
        result = base._render_with_templar(sentinel, templar=None, variables={"x": 1})
        self.assertIs(result, sentinel)


class TestResolveOverrideMapping(unittest.TestCase):
    def test_missing_key_returns_empty_dict(self):
        self.assertEqual(base._resolve_override_mapping({}, "applications"), {})

    def test_mapping_passes_through(self):
        result = base._resolve_override_mapping(
            {"applications": {"web-app-x": {"foo": 1}}}, "applications"
        )
        self.assertEqual(result, {"web-app-x": {"foo": 1}})

    def test_falls_back_to_raw_inventory_when_value_is_not_mapping(self):
        result = base._resolve_override_mapping(
            {
                "applications": "<placeholder>",
                "_INFINITO_APPLICATIONS_RAW": {"web-app-x": {"foo": 1}},
            },
            "applications",
        )
        self.assertEqual(result, {"web-app-x": {"foo": 1}})


class TestFingerprintIsContentOnly(unittest.TestCase):
    def test_fingerprint_survives_reset_because_it_holds_no_state(self):
        before = base._fingerprint_mapping({"a": 1})
        _reset_cache_for_tests()
        self.assertEqual(before, base._fingerprint_mapping({"a": 1}))


if __name__ == "__main__":
    unittest.main()
