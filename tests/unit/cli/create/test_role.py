"""Unit tests for ``cli.create.role``.

The post-req-009 CLI auto-allocates the per-role subnet via
``cli meta networks suggest`` and per-entity port slots via
``cli meta ports suggest``. Network and port assignments live in the
new per-role meta layout (``meta/server.yml`` and ``meta/services.yml``).
"""

from __future__ import annotations

import builtins
import shutil
import tempfile
import unittest

from cli.create.role.__main__ import render_templates


class TestRenderTemplates(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_render_creates_and_overwrites_skips_merges(self) -> None:
        from pathlib import Path

        src = Path(self.tmpdir) / "src"
        dst = Path(self.tmpdir) / "dst"
        src.mkdir()
        dst.mkdir()

        tpl = src / "file.txt.j2"
        tpl.write_text("Line1\nLine2", encoding="utf-8")
        out_file = dst / "file.txt"

        # Create
        render_templates(src, dst, {})
        self.assertEqual(out_file.read_text(encoding="utf-8"), "Line1\nLine2")

        # Overwrite
        out_file.write_text("Old", encoding="utf-8")
        original_input = builtins.input
        builtins.input = lambda _: "1"
        try:
            render_templates(src, dst, {})
            self.assertEqual(out_file.read_text(encoding="utf-8"), "Line1\nLine2")

            # Skip
            out_file.write_text("Old", encoding="utf-8")
            builtins.input = lambda _: "2"
            render_templates(src, dst, {})
            self.assertEqual(out_file.read_text(encoding="utf-8"), "Old")

            # Merge
            out_file.write_text("Line1\n", encoding="utf-8")
            builtins.input = lambda _: "3"
            render_templates(src, dst, {})
            content = out_file.read_text(encoding="utf-8").splitlines()
            self.assertIn("Line1", content)
            self.assertIn("Line2", content)
        finally:
            builtins.input = original_input


class TestSuggesterIntegration(unittest.TestCase):
    """The CLI auto-allocates subnets and ports via the live role tree.
    These tests pin the contract of the wired-in helpers; behaviour is
    covered exhaustively in cli/meta/{ports,networks}/suggest tests."""

    def test_suggest_subnets_returns_a_cidr(self) -> None:
        from cli.meta.networks.suggest.__main__ import (
            capacity_for,
            suggest_subnets,
        )

        suggestions, gaps = suggest_subnets(clients=14, count=1, explicit_block=None)
        self.assertEqual(len(suggestions), 1)
        self.assertGreaterEqual(capacity_for(suggestions[0]), 14)
        self.assertGreaterEqual(gaps, 1)

    def test_suggest_single_ports_returns_band_member(self) -> None:
        from cli.meta.ports.suggest.__main__ import suggest_single_ports
        from utils.meta.port_bands import lookup_band

        suggestions, _gaps = suggest_single_ports(
            scope="local",
            category="http",
            count=1,
            explicit_range=None,
        )
        band = lookup_band("local", "http")
        self.assertIsNotNone(band)
        self.assertGreaterEqual(suggestions[0], band[0])
        self.assertLessEqual(suggestions[0], band[1])


if __name__ == "__main__":
    unittest.main()
