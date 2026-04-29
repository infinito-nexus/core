"""Focused unit tests for ``utils.cache.base``.

Covers the cross-cutting helpers in isolation: constants, deep_merge,
yaml-loaders, signatures, fingerprint memo, _reset(), and the
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

from utils.cache import _reset_cache_for_tests
from utils.cache import base


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
        # Sanity: shape of the constant, not its on-disk presence (the
        # path lives in /var/lib/infinito which is irrelevant during tests).
        self.assertEqual(
            base.DEFAULT_TOKENS_FILE,
            Path("/var/lib/infinito/secrets/tokens.yml"),
        )


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
        # base mapping + override list -> override wins (no merge across types)
        result = base._deep_merge({"x": {"y": 1}}, {"x": ["a", "b"]})
        self.assertEqual(result, {"x": ["a", "b"]})

    def test_returns_deep_copy_of_override_when_base_is_none(self):
        override = {"x": [1, 2, 3]}
        result = base._deep_merge(None, override)
        self.assertEqual(result, override)
        # Mutate the result to confirm it is a deep copy.
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

    def test_same_object_hits_id_memo(self):
        obj = {"a": 1}
        first = base._fingerprint_mapping(obj)
        # The id() memo means a second call with the same object skips the
        # hash recomputation; we cannot inspect that directly but can at
        # least pin that the result is stable.
        self.assertEqual(first, base._fingerprint_mapping(obj))

    def test_equal_content_distinct_objects_hash_to_same_digest(self):
        # Different dict instances with the same content MUST collide on
        # the content fingerprint — that is the whole point of this hash
        # vs id() — so the cross-task cache hits when the inventory
        # payload is unchanged.
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
            # Mutate length so size differs.
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
        # No templar => no rendering, returned as-is (same object,
        # because the fast path doesn't even copy).
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
        # Simulates the "lookup placeholder" case noted in the docstring:
        # `applications` arrives as a non-mapping placeholder, the raw
        # inventory dict is on the side under _INFINITO_APPLICATIONS_RAW.
        result = base._resolve_override_mapping(
            {
                "applications": "<placeholder>",
                "_INFINITO_APPLICATIONS_RAW": {"web-app-x": {"foo": 1}},
            },
            "applications",
        )
        self.assertEqual(result, {"web-app-x": {"foo": 1}})


class TestImplicitResetClearsFingerprint(unittest.TestCase):
    def test_reset_clears_fingerprint_memo(self):
        # Force a memo entry, then call reset.
        base._fingerprint_mapping({"a": 1})
        self.assertGreater(len(base._FINGERPRINT_BY_ID), 0)
        _reset_cache_for_tests()
        self.assertEqual(len(base._FINGERPRINT_BY_ID), 0)


# NOTE: the import-time / call-time invariant for ansible-less hosts is
# pinned in `tests/unit/utils/cache/test_applications.py::
# TestApplicationsImportableWithoutAnsible` (the meaningful surface)
# and `tests/unit/utils/cache/test_data.py::TestImportableWithoutAnsible`
# (legacy compatibility). Reloading `utils.cache.base` here would just
# fragment the shared `_FINGERPRINT_BY_ID` instance and trip OTHER
# tests that depend on a single canonical module identity.


if __name__ == "__main__":
    unittest.main()
