import tempfile
import unittest
from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from cli.administration.inventory.provision.ruamel_io import (
    as_commented_map,
    dump_document,
    ensure_map,
    load_document,
)


class TestAsCommentedMap(unittest.TestCase):
    """The migration branch every writer in the package relies on."""

    def test_a_mapping_is_returned_unchanged(self):
        original = CommentedMap()
        original["a"] = 1

        self.assertIs(original, as_commented_map(original))

    def test_none_becomes_an_empty_map(self):
        self.assertEqual(CommentedMap(), as_commented_map(None))

    def test_a_plain_dict_is_migrated(self):
        migrated = as_commented_map({"a": 1, "b": {"c": 2}})

        self.assertIsInstance(migrated, CommentedMap)
        self.assertEqual(1, migrated["a"])
        self.assertEqual({"c": 2}, migrated["b"])

    def test_a_sequence_root_aborts_rather_than_silently_emptying(self):
        with self.assertRaises((TypeError, ValueError)):
            as_commented_map([1, 2, 3])


class TestLoadDocument(unittest.TestCase):
    def test_a_missing_file_yields_an_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                CommentedMap(), load_document(Path(tmp) / "absent.yml")
            )

    def test_an_empty_file_yields_an_empty_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.yml"
            path.write_text("", encoding="utf-8")

            self.assertEqual(CommentedMap(), load_document(path))

    def test_a_sequence_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "list.yml"
            path.write_text("- a\n- b\n", encoding="utf-8")

            with self.assertRaises((TypeError, ValueError)):
                load_document(path)


class TestDumpDocument(unittest.TestCase):
    def test_a_missing_parent_directory_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "deeper" / "host.yml"
            document = CommentedMap()
            document["a"] = 1

            dump_document(path, document)

            self.assertTrue(path.exists())
            self.assertEqual(1, load_document(path)["a"])


class TestEnsureMap(unittest.TestCase):
    def test_a_missing_key_is_created(self):
        node = CommentedMap()

        child = ensure_map(node, "users")

        self.assertIsInstance(child, CommentedMap)
        self.assertIs(child, node["users"])

    def test_an_existing_map_is_reused(self):
        node = CommentedMap()
        existing = CommentedMap()
        existing["keep"] = True
        node["users"] = existing

        self.assertIs(existing, ensure_map(node, "users"))

    def test_a_non_map_value_is_replaced(self):
        node = CommentedMap()
        node["users"] = "not-a-map"

        child = ensure_map(node, "users")

        self.assertIsInstance(child, CommentedMap)
        self.assertEqual(CommentedMap(), child)


if __name__ == "__main__":
    unittest.main()
