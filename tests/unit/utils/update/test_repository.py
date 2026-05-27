from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.update.repository import (
    RepositoryRefEntry,
    RepositoryRefUpdate,
    apply_updates,
    suppressed_ref_lines,
    update_config_refs,
    walk_repo_ref_pairs,
)


class TestWalkRepoRefPairs(unittest.TestCase):
    def test_finds_top_level_entity(self) -> None:
        data = {
            "bookwyrm": {
                "repository": "https://github.com/bookwyrm-social/bookwyrm.git",
                "ref": "v0.8.5",
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(
            pairs,
            [
                (
                    ("bookwyrm",),
                    "https://github.com/bookwyrm-social/bookwyrm.git",
                    "v0.8.5",
                ),
            ],
        )

    def test_descends_into_nested_plugin_map(self) -> None:
        # Discourse-style plugin nesting: discourse.plugins.<name>.repository+ref
        data = {
            "discourse": {
                "plugins": {
                    "discourse-ldap-auth": {
                        "repository": "https://github.com/jonmbake/discourse-ldap-auth.git",
                        "ref": "master",
                    },
                    "discourse-prometheus": {
                        "repository": "https://github.com/discourse/discourse-prometheus.git",
                        "ref": "v1.0.0",
                    },
                },
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))
        entity_paths = {pair[0] for pair in pairs}

        self.assertIn(("discourse", "plugins", "discourse-ldap-auth"), entity_paths)
        self.assertIn(("discourse", "plugins", "discourse-prometheus"), entity_paths)

    def test_skips_when_only_repository_or_only_ref(self) -> None:
        data = {
            "only-repo": {"repository": "https://example.invalid/x.git"},
            "only-ref": {"ref": "v1.0.0"},
            "both": {
                "repository": "https://example.invalid/y.git",
                "ref": "v2.0.0",
            },
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], ("both",))

    def test_walks_lists(self) -> None:
        data = {
            "repos": [
                {
                    "repository": "https://example.invalid/a.git",
                    "ref": "v1",
                },
                {
                    "repository": "https://example.invalid/b.git",
                    "ref": "v2",
                },
            ],
        }

        pairs = list(walk_repo_ref_pairs(data, ()))

        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][0], ("repos", "[0]"))
        self.assertEqual(pairs[1][0], ("repos", "[1]"))


class TestUpdateConfigRefs(unittest.TestCase):
    def test_rewrites_target_line_and_preserves_others(self) -> None:
        original = """plugin-a:
  repository: https://example.invalid/a.git
  ref: v1.0.0
plugin-b:
  repository: https://example.invalid/b.git
  ref: v2.0.0
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            # plugin-a's `ref:` is on line 3.
            changed = update_config_refs(config_path, {3: "v1.1.0"})

            self.assertTrue(changed)
            updated = read_text(str(config_path))
            self.assertIn("  ref: v1.1.0\n", updated)
            self.assertIn("  ref: v2.0.0\n", updated)

    def test_preserves_quoting_and_trailing_comment(self) -> None:
        original = '  ref: "v0.7.5"  # pin\n'
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {1: "v0.8.5"})

            self.assertTrue(changed)
            self.assertEqual(
                read_text(str(config_path)),
                '  ref: "v0.8.5"  # pin\n',
            )

    def test_no_op_when_target_value_already_matches(self) -> None:
        original = "  ref: v1.0.0\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {1: "v1.0.0"})

            self.assertFalse(changed)
            self.assertEqual(read_text(str(config_path)), original)

    def test_skips_out_of_range_line_numbers(self) -> None:
        original = "  ref: v1.0.0\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_refs(config_path, {99: "v2.0.0"})

            self.assertFalse(changed)
            self.assertEqual(read_text(str(config_path)), original)


class TestSuppressedRefLines(unittest.TestCase):
    def test_recognises_line_above_marker(self) -> None:
        content = """plugin-a:
  repository: https://example.invalid/a.git
  # nocheck: repository-version
  ref: v1.0.0
plugin-b:
  repository: https://example.invalid/b.git
  ref: v2.0.0
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "services.yml"
            config_path.write_text(content, encoding="utf-8")

            suppressed = suppressed_ref_lines(config_path)

            # plugin-a's `ref:` sits on line 4 and is suppressed.
            self.assertEqual(suppressed, {4})


class TestApplyUpdates(unittest.TestCase):
    def test_groups_updates_per_config_file(self) -> None:
        file_a_content = "  ref: v1.0.0\n"
        file_b_content = "  ref: v2.0.0\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            config_a = Path(tmpdir) / "a" / "services.yml"
            config_b = Path(tmpdir) / "b" / "services.yml"
            config_a.parent.mkdir()
            config_b.parent.mkdir()
            config_a.write_text(file_a_content, encoding="utf-8")
            config_b.write_text(file_b_content, encoding="utf-8")

            updates = [
                RepositoryRefUpdate(
                    entry=RepositoryRefEntry(
                        role="role-a",
                        entity_path=("plugin-a",),
                        repository="https://example.invalid/a.git",
                        ref="v1.0.0",
                        config_path=config_a,
                        line=1,
                    ),
                    latest="v1.1.0",
                ),
                RepositoryRefUpdate(
                    entry=RepositoryRefEntry(
                        role="role-b",
                        entity_path=("plugin-b",),
                        repository="https://example.invalid/b.git",
                        ref="v2.0.0",
                        config_path=config_b,
                        line=1,
                    ),
                    latest="v2.1.0",
                ),
            ]

            changed = apply_updates(updates)

            self.assertEqual(set(changed), {config_a, config_b})
            self.assertEqual(read_text(str(config_a)), "  ref: v1.1.0\n")
            self.assertEqual(read_text(str(config_b)), "  ref: v2.1.0\n")


if __name__ == "__main__":
    unittest.main()
