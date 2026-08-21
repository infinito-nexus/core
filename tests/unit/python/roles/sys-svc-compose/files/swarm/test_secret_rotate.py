import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from utils.cache.yaml import dump_yaml, load_yaml

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class SecretRotateMixin:
    def setUp(self) -> None:
        super().setUp()
        self.m = _load_module(
            "roles/sys-svc-compose/files/python/swarm/secret_rotate.py",
            "swarm_secret_rotate_mod",
        )
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_source(self, name: str, content: str) -> Path:
        path = self.tmp / name
        path.write_text(content, encoding="utf-8")
        return path

    def rotate(self, doc: dict) -> dict:
        compose = self.tmp / "compose.yml"
        dump_yaml(compose, doc)
        self.assertEqual(self.m.rotate(compose), 0)
        return load_yaml(compose)


class ContentHashTests(SecretRotateMixin, unittest.TestCase):
    def test_it_is_the_sha256_prefix_of_the_file(self):
        path = self.write_source("secret.txt", "hunter2")
        expected = hashlib.sha256(b"hunter2").hexdigest()[:8]
        self.assertEqual(self.m.content_hash(path), expected)

    def test_it_is_eight_characters_by_default(self):
        path = self.write_source("secret.txt", "hunter2")
        self.assertEqual(len(self.m.content_hash(path)), 8)

    def test_a_different_length_is_honoured(self):
        path = self.write_source("secret.txt", "hunter2")
        self.assertEqual(len(self.m.content_hash(path, length=12)), 12)

    def test_the_same_content_hashes_the_same(self):
        first = self.write_source("a.txt", "same")
        second = self.write_source("b.txt", "same")
        self.assertEqual(self.m.content_hash(first), self.m.content_hash(second))

    def test_changed_content_changes_the_hash(self):
        path = self.write_source("secret.txt", "before")
        before = self.m.content_hash(path)
        path.write_text("after", encoding="utf-8")
        self.assertNotEqual(before, self.m.content_hash(path))

    def test_a_binary_secret_still_hashes(self):
        """A TLS key or keytab is not UTF-8; the byte fallback must cover it."""
        path = self.tmp / "keytab"
        path.write_bytes(b"\xff\xfe\x00binary")
        self.assertEqual(
            self.m.content_hash(path),
            hashlib.sha256(b"\xff\xfe\x00binary").hexdigest()[:8],
        )


class HashSuffixPatternTests(SecretRotateMixin, unittest.TestCase):
    def test_it_matches_an_eight_digit_hex_suffix(self):
        match = self.m.HASH_SUFFIX_RE.match("app_secret_deadbeef")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("prefix"), "app_secret")

    def test_a_name_without_a_suffix_does_not_match(self):
        self.assertIsNone(self.m.HASH_SUFFIX_RE.match("app_secret"))

    def test_a_short_suffix_does_not_match(self):
        self.assertIsNone(self.m.HASH_SUFFIX_RE.match("app_secret_dead"))

    def test_a_non_hex_suffix_does_not_match(self):
        self.assertIsNone(self.m.HASH_SUFFIX_RE.match("app_secret_zzzzzzzz"))


class RotateTests(SecretRotateMixin, unittest.TestCase):
    def _doc(self, section: str, source: Path, name: str) -> dict:
        return {section: {"entry": {"file": str(source), "name": name}}}

    def test_a_stale_name_is_rotated_to_the_current_hash(self):
        source = self.write_source("secret.txt", "fresh")
        digest = self.m.content_hash(source)
        result = self.rotate(self._doc("secrets", source, "app_00000000"))
        self.assertEqual(result["secrets"]["entry"]["name"], f"app_{digest}")

    def test_a_current_name_is_left_untouched(self):
        source = self.write_source("secret.txt", "fresh")
        name = f"app_{self.m.content_hash(source)}"
        result = self.rotate(self._doc("secrets", source, name))
        self.assertEqual(result["secrets"]["entry"]["name"], name)

    def test_configs_are_rotated_as_well_as_secrets(self):
        source = self.write_source("config.txt", "fresh")
        digest = self.m.content_hash(source)
        result = self.rotate(self._doc("configs", source, "cfg_00000000"))
        self.assertEqual(result["configs"]["entry"]["name"], f"cfg_{digest}")

    def test_a_name_without_a_hash_suffix_is_never_rewritten(self):
        source = self.write_source("secret.txt", "fresh")
        result = self.rotate(self._doc("secrets", source, "plain_name"))
        self.assertEqual(result["secrets"]["entry"]["name"], "plain_name")

    def test_a_missing_source_leaves_the_name_alone(self):
        """Rotating to the hash of a file that is not there would pin a lie."""
        missing = self.tmp / "gone.txt"
        result = self.rotate(self._doc("secrets", missing, "app_00000000"))
        self.assertEqual(result["secrets"]["entry"]["name"], "app_00000000")

    def test_the_prefix_survives_rotation(self):
        source = self.write_source("secret.txt", "fresh")
        result = self.rotate(self._doc("secrets", source, "some_long_prefix_00000000"))
        self.assertTrue(
            result["secrets"]["entry"]["name"].startswith("some_long_prefix_")
        )

    def test_an_entry_without_a_file_key_is_skipped(self):
        result = self.rotate({"secrets": {"entry": {"name": "app_00000000"}}})
        self.assertEqual(result["secrets"]["entry"]["name"], "app_00000000")

    def test_a_document_that_is_not_a_mapping_is_a_no_op(self):
        compose = self.tmp / "compose.yml"
        compose.write_text("- not a mapping\n", encoding="utf-8")
        self.assertEqual(self.m.rotate(compose), 0)
        text = compose.read_text(encoding="utf-8")  # nocheck: cache-read  tempdir
        self.assertEqual(text, "- not a mapping\n")

    def test_an_unchanged_document_is_not_rewritten(self):
        source = self.write_source("secret.txt", "fresh")
        name = f"app_{self.m.content_hash(source)}"
        compose = self.tmp / "compose.yml"
        dump_yaml(compose, self._doc("secrets", source, name))
        before = compose.stat().st_mtime_ns
        self.m.rotate(compose)
        self.assertEqual(compose.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
