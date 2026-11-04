from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cli.build.docs.lifecycle import BEGIN, END, render, replace_block
from cli.build.docs.lifecycle.__main__ import main
from utils.roles import lifecycle

_SPEC = {
    "contexts": {
        "main": {
            "description": "Upstream main.",
            "repository": "infinito-nexus/core",
            "refs": ["refs/heads/main"],
            "events": ["push"],
        },
        "rest": {"description": "Everything else."},
    },
    "statuses": {
        "a": {"description": "Entry."},
        "b": {
            "description": "Second.",
            "predecessors": ["a"],
            "flags": ["production"],
            "ci-deploy": ["main", "rest"],
        },
        "c": {
            "description": "Third.",
            "predecessors": ["a", "b"],
            "flags": ["retired"],
        },
    },
}


def _spot(spec: dict) -> lifecycle.Lifecycle:
    spot, errors = lifecycle.parse(spec)
    assert not errors, errors
    return spot


def _doc(block: str) -> str:
    return f"# Title\n\nintro\n\n{BEGIN}\n{block}\n{END}\n\nafter\n"


class TestRender(unittest.TestCase):
    def test_every_edge_and_flag_is_drawn(self) -> None:
        text = render(_spot(_SPEC))
        self.assertIn('s_b["b<br>production"]', text)
        self.assertIn('s_c["c<br>retired"]', text)
        self.assertIn("s_a --> s_b", text)
        self.assertIn("s_a --> s_c", text)
        self.assertIn("s_b --> s_c", text)
        self.assertIn("c_main -.-> s_b", text)
        self.assertIn("c_rest -.-> s_b", text)
        self.assertNotIn("-.-> s_a", text)

    def test_a_changed_predecessor_changes_the_render(self) -> None:
        moved = {**_SPEC, "statuses": {**_SPEC["statuses"]}}
        moved["statuses"]["c"] = {**moved["statuses"]["c"], "predecessors": ["b"]}
        self.assertNotEqual(render(_spot(_SPEC)), render(_spot(moved)))
        self.assertNotIn("s_a --> s_c", render(_spot(moved)))

    def test_a_changed_context_changes_the_render(self) -> None:
        moved = {**_SPEC, "statuses": {**_SPEC["statuses"]}}
        moved["statuses"]["b"] = {**moved["statuses"]["b"], "ci-deploy": ["rest"]}
        self.assertNotIn("c_main -.-> s_b", render(_spot(moved)))


class TestReplaceBlock(unittest.TestCase):
    def test_only_the_block_between_the_markers_changes(self) -> None:
        updated = replace_block(_doc("stale"), "fresh")
        self.assertIn("fresh", updated)
        self.assertNotIn("stale", updated)
        self.assertTrue(updated.startswith("# Title\n\nintro\n\n"))
        self.assertTrue(updated.endswith("\nafter\n"))

    def test_an_empty_committed_block_is_filled(self) -> None:
        updated = replace_block(f"{BEGIN}\n{END}\n", "fresh")
        self.assertEqual(f"{BEGIN}\n\nfresh\n\n{END}\n", updated)

    def test_the_replacement_is_idempotent(self) -> None:
        once = replace_block(_doc("stale"), "fresh")
        self.assertEqual(once, replace_block(once, "fresh"))

    def test_missing_or_reversed_markers_raise(self) -> None:
        with self.assertRaises(ValueError):
            replace_block("# no markers\n", "x")
        with self.assertRaises(ValueError):
            replace_block(f"{END}\n{BEGIN}\n", "x")


class TestMain(unittest.TestCase):
    def test_main_renders_the_spot_into_the_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            doc = Path(tmp) / "lifecycle.md"
            doc.write_text(f"# T\n{BEGIN}\n{END}\n", encoding="utf-8")
            self.assertEqual(0, main(["--doc", str(doc)]))
            written = doc.read_text(encoding="utf-8")  # nocheck: cache-read
        self.assertIn("flowchart LR", written)
        self.assertIn("c_upstream_main -.-> s_beta", written)
        self.assertNotIn("c_upstream_main -.-> s_alpha", written)


if __name__ == "__main__":
    unittest.main()
