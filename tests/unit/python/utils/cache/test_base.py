"""Focused unit tests for ``utils.cache.base``.

Covers the cross-cutting helpers in isolation: constants, deep_merge,
yaml-loaders, signatures, content fingerprints, _reset(), and the
templar-render machinery (with both no-templar and stub-templar
inputs). The broader integration of these helpers via the
applications/users/domains paths is covered in the per-domain test
files; this file pins the contract of base itself.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import textwrap
import threading
import unittest
import unittest.mock as mock
import weakref
from pathlib import Path

from utils.cache import PROJECT_ROOT, base
from utils.cache.reset import _reset_cache_for_tests
from utils.domains.default_primary import default_domain_primary
from utils.paths import FILE_TOKENS

DOMAIN = default_domain_primary()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def _repr_digest(obj: dict) -> str:
    return hashlib.md5(
        repr(sorted(obj.items())).encode("utf-8", errors="replace"),
        usedforsecurity=False,
    ).hexdigest()


def _mapping_calls(spy: mock.MagicMock) -> int:
    return sum(1 for call in spy.call_args_list if call.args[0] is not None)


class TestProjectRootInvariants(unittest.TestCase):
    """`PROJECT_ROOT` must point at the actual repo root, not at
    `<repo>/utils/`. CI run 24934007615 was caused by exactly this
    drift after `utils/cache/data.py` was moved one level deeper.
    """

    def test_project_root_resolves_to_repo_root(self):
        self.assertTrue((PROJECT_ROOT / "roles").is_dir())
        self.assertTrue((PROJECT_ROOT / "cli").is_dir())
        self.assertEqual(base.ROLES_DIR, PROJECT_ROOT / "roles")

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

    def test_an_equal_value_of_another_type_changes_the_digest(self):
        obj = {"web-app-x": {"port": 1, "ratio": 0.0}}
        digests = [base._fingerprint_mapping(obj)]
        for key, value in (("port", True), ("port", 1.0), ("ratio", -0.0)):
            obj["web-app-x"][key] = value
            digests.append(base._fingerprint_mapping(obj))

        self.assertEqual(len(digests), len(set(digests)))

    def test_nested_key_order_changes_the_digest_as_repr_does(self):
        first = base._fingerprint_mapping({"a": {"x": 1, "y": 2}})
        second = base._fingerprint_mapping({"a": {"y": 2, "x": 1}})

        self.assertNotEqual(first, second)


class _WeakDict(dict):
    pass


class _CountingTemplar:
    def __init__(self, variables: dict) -> None:
        self.available_variables = variables
        self.signatures: list[tuple] = []

    def template(self, data, **_kwargs):
        self.signatures.append(
            base._stable_variables_signature(self.available_variables)
        )
        return data


class TestScopedFingerprint(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def _signature(self, applications) -> str:
        return base._stable_variables_signature({"applications": applications})[0]

    def test_outside_a_scope_every_call_fingerprints(self):
        obj = {"web-app-x": {"port": 1}}
        with mock.patch.object(
            base, "_fingerprint_mapping", wraps=base._fingerprint_mapping
        ) as spy:
            self._signature(obj)
            self._signature(obj)

        self.assertEqual(2, _mapping_calls(spy))

    def test_a_scope_fingerprints_a_mapping_once_and_checks_it_on_exit(self):
        obj = {"web-app-x": {"port": 1}}
        with (
            mock.patch.object(
                base, "_fingerprint_mapping", wraps=base._fingerprint_mapping
            ) as spy,
            base._fingerprint_scope(),
        ):
            digests = {self._signature(obj) for _ in range(50)}

        self.assertEqual({_repr_digest(obj)}, digests)
        self.assertEqual(2, _mapping_calls(spy))

    def test_a_freed_mapping_never_answers_for_a_new_one_inside_a_scope(self):
        with base._fingerprint_scope():
            digests = []
            for i in range(400):
                transient = {"web-app-x": {"port": i}}
                digests.append(self._signature(transient))
                self.assertEqual(_repr_digest(transient), digests[-1])
                del transient

        self.assertEqual(400, len(set(digests)))

    def test_a_reused_address_across_scopes_gets_its_own_digest(self):
        by_address: dict[int, list[str]] = {}
        for i in range(400):
            transient = {"web-app-x": {"port": i}}
            with base._fingerprint_scope():
                digest = self._signature(transient)
            self.assertEqual(_repr_digest(transient), digest)
            by_address.setdefault(id(transient), []).append(digest)
            del transient

        for address, digests in by_address.items():
            with self.subTest(address=address, reuses=len(digests)):
                self.assertEqual(len(digests), len(set(digests)))

    def test_in_place_mutation_between_two_renders_changes_the_key(self):
        obj = {"web-app-x": {"server": {"domains": ["a.test"]}}}
        with base._fingerprint_scope():
            first = self._signature(obj)
            self._signature(obj)

        obj["web-app-x"]["server"]["domains"].append("b.test")

        with base._fingerprint_scope():
            second = self._signature(obj)

        self.assertNotEqual(first, second)
        self.assertEqual(_repr_digest(obj), second)

    def test_the_released_guard_holds_no_mapping(self):
        obj = _WeakDict({"web-app-x": {"port": 1}})
        ref = weakref.ref(obj)
        with base._fingerprint_scope():
            self._signature(obj)
            self._signature(obj)

        self.assertIsNone(getattr(base._RENDER_GUARD, "fingerprints", None))
        del obj
        self.assertIsNone(ref(), "the scope kept the mapping alive after release")

    def test_in_place_mutation_inside_a_render_raises(self):
        obj = {"web-app-x": {"port": 1}}
        with (
            self.assertRaises(base.ScopedFingerprintMutatedError),
            base._fingerprint_scope(),
        ):
            self._signature(obj)
            self._signature(obj)
            obj["web-app-x"]["port"] = True

        self.assertIsNone(getattr(base._RENDER_GUARD, "fingerprints", None))

    def test_a_nested_scope_joins_the_outer_one(self):
        obj = {"web-app-x": {"port": 1}}
        with (
            self.assertRaises(base.ScopedFingerprintMutatedError),
            base._fingerprint_scope(),
        ):
            self._signature(obj)
            with base._fingerprint_scope():
                self._signature(obj)
                obj["web-app-x"]["port"] = 2
            self.assertIsNotNone(base._RENDER_GUARD.fingerprints)

    def test_a_failing_render_releases_the_guard(self):
        with self.assertRaises(KeyError), base._fingerprint_scope():
            self._signature({"web-app-x": {}})
            raise KeyError("render failed")

        self.assertIsNone(getattr(base._RENDER_GUARD, "fingerprints", None))

    def test_a_failing_render_keeps_its_own_error_over_a_mutation(self):
        obj = {"web-app-x": {"port": 1}}
        with self.assertRaises(KeyError) as caught, base._fingerprint_scope():
            self._signature(obj)
            self._signature(obj)
            obj["web-app-x"]["port"] = 2
            raise KeyError("render failed")

        self.assertEqual(("render failed",), caught.exception.args)
        self.assertIsNone(getattr(base._RENDER_GUARD, "fingerprints", None))

    def test_a_scope_in_one_thread_is_invisible_in_another(self):
        obj = {"web-app-x": {"port": 1}}
        opened = threading.Event()
        probed = threading.Event()
        calls: dict[str, list] = {"a": [], "b": []}
        seen: dict[str, object] = {}
        real = base._fingerprint_mapping

        def spy(value):
            if value is not None:
                calls[threading.current_thread().name].append(value)
            return real(value)

        def thread_a():
            with base._fingerprint_scope():
                seen["a_first"] = self._signature(obj)
                opened.set()
                probed.wait(timeout=10)
                seen["a_second"] = self._signature(obj)

        def thread_b():
            opened.wait(timeout=10)
            seen["b_guard"] = getattr(base._RENDER_GUARD, "fingerprints", None)
            seen["b_first"] = self._signature(obj)
            seen["b_second"] = self._signature(obj)
            probed.set()

        with mock.patch.object(base, "_fingerprint_mapping", side_effect=spy):
            workers = [
                threading.Thread(target=thread_a, name="a"),
                threading.Thread(target=thread_b, name="b"),
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=10)

        self.assertIsNone(seen["b_guard"])
        self.assertEqual(2, len(calls["b"]))
        self.assertEqual(2, len(calls["a"]))
        self.assertEqual(
            {_repr_digest(obj)},
            {seen[k] for k in ("a_first", "a_second", "b_first", "b_second")},
        )

    def test_render_with_templar_keys_its_nested_lookups_once(self):
        applications = {"web-app-x": {"port": 1}}
        templar = _CountingTemplar({"applications": applications})
        value = {
            "a": "{{ x }}",
            "b": ["{{ y }}", "{{ z }}"],
            "c": "{% if w %}{% endif %}",
        }
        with mock.patch.object(
            base, "_fingerprint_mapping", wraps=base._fingerprint_mapping
        ) as spy:
            base._render_with_templar(value, templar=templar, variables={})

        self.assertGreaterEqual(len(templar.signatures), 4)
        self.assertEqual(1, len(set(templar.signatures)))
        self.assertEqual(_repr_digest(applications), templar.signatures[0][0])
        self.assertEqual(2, _mapping_calls(spy))


class TestStableVariablesSignature(unittest.TestCase):
    def setUp(self) -> None:
        _reset_cache_for_tests()

    def test_empty_variables_collapses_to_canonical_tuple(self):
        self.assertEqual(
            base._stable_variables_signature(None),
            ("0", "0", "", "", ""),
        )
        self.assertEqual(
            base._stable_variables_signature({}),
            ("0", "0", "", "", ""),
        )

    def test_two_hosts_of_one_play_do_not_share_a_key(self):
        shared = {"applications": {"web-app-pretix": {}}, "DOMAIN_PRIMARY": "x.test"}
        member = base._stable_variables_signature(
            {**shared, "group_names": ["web-app-pretix", "svc-db-postgres"]}
        )
        outsider = base._stable_variables_signature(
            {**shared, "group_names": ["web-app-pretix"]}
        )

        self.assertNotEqual(
            member,
            outsider,
            "a service flag may read group_names, so one host's payload must "
            "never answer for a host whose groups differ",
        )

    def test_group_order_does_not_split_the_key(self):
        first = base._stable_variables_signature({"group_names": ["a", "b"]})
        second = base._stable_variables_signature({"group_names": ["b", "a"]})

        self.assertEqual(first, second)

    def test_includes_domain_primary_and_email_domain_strings(self):
        sig = base._stable_variables_signature(
            {
                "applications": {"web-app-x": {}},
                "DOMAIN_PRIMARY": DOMAIN,
                "SYSTEM_EMAIL_DOMAIN": f"mail.{DOMAIN}",
            }
        )
        self.assertEqual(sig[2], DOMAIN)
        self.assertEqual(sig[3], f"mail.{DOMAIN}")


class TestTokensFileSignature(unittest.TestCase):
    def setUp(self):
        base._reset()

    def test_missing_file_returns_an_empty_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "absent.yml"
            self.assertEqual(base._tokens_file_signature(path), (str(path), ""))

    def test_signature_changes_when_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text("a: 1\n", encoding="utf-8")
            sig_before = base._tokens_file_signature(path)
            path.write_text("a: 1\nb: 2\n", encoding="utf-8")
            sig_after = base._tokens_file_signature(path)
            self.assertNotEqual(sig_before, sig_after)

    def test_a_touch_keeps_the_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text("a: 1\n", encoding="utf-8")
            sig_before = base._tokens_file_signature(path)
            later = path.stat().st_mtime_ns + 5_000_000_000
            os.utime(path, ns=(later, later))
            self.assertEqual(base._tokens_file_signature(path), sig_before)

    def test_an_unchanged_stat_serves_the_digest_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text("a: 1\n", encoding="utf-8")
            sig_before = base._tokens_file_signature(path)
            with mock.patch.object(Path, "open", side_effect=AssertionError):
                self.assertEqual(base._tokens_file_signature(path), sig_before)


class TestRevalidateTokensFile(unittest.TestCase):
    def test_opens_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tokens.yml"
            path.write_text("a: 1\n", encoding="utf-8")
            with mock.patch.object(Path, "open", wraps=path.open) as opened:
                base._revalidate_tokens_file(path)
            opened.assert_called_once_with("rb")

    def test_a_missing_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            base._revalidate_tokens_file(Path(tmp) / "absent.yml")


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
