"""Unit tests for `utils.inventory.bundle_apps`."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils.cache.yaml import _reset_cache_for_tests
from utils.inventory import bundle_apps


class TestSplitCsv(unittest.TestCase):
    def test_splits_and_trims(self):
        self.assertEqual(
            bundle_apps._split_csv(" a , b,c "),
            ["a", "b", "c"],
        )

    def test_drops_empty_segments(self):
        self.assertEqual(bundle_apps._split_csv("a,,b,"), ["a", "b"])

    def test_empty_string(self):
        self.assertEqual(bundle_apps._split_csv(""), [])


class _BundleFsMixin:
    """Build a fake inventories/bundles tree and patch SEARCH_DIRS."""

    def setUp(self) -> None:  # type: ignore[override]
        _reset_cache_for_tests()
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)  # type: ignore[attr-defined]
        root = Path(self._tmp.name)
        self.servers = root / "servers"
        self.workstations = root / "workstations"
        self.servers.mkdir()
        self.workstations.mkdir()
        patcher = patch.object(
            bundle_apps,
            "SEARCH_DIRS",
            (self.servers, self.workstations),
        )
        patcher.start()
        self.addCleanup(patcher.stop)  # type: ignore[attr-defined]

    def write_bundle(self, base: Path, name: str, apps: list[str]) -> Path:
        bundle_dir = base / name
        bundle_dir.mkdir()
        inv = bundle_dir / "inventory.yml"
        children = "".join(f"    {a}:\n" for a in apps) or "    {}\n"
        inv.write_text(f"all:\n  children:\n{children}", encoding="utf-8")
        return inv


class TestLocate(_BundleFsMixin, unittest.TestCase):
    def test_finds_in_servers(self):
        self.write_bundle(self.servers, "alpha", ["a"])
        self.assertEqual(
            bundle_apps._locate("alpha"),
            self.servers / "alpha" / "inventory.yml",
        )

    def test_finds_in_workstations(self):
        self.write_bundle(self.workstations, "beta", ["b"])
        self.assertEqual(
            bundle_apps._locate("beta"),
            self.workstations / "beta" / "inventory.yml",
        )

    def test_servers_wins_over_workstations(self):
        self.write_bundle(self.servers, "dup", ["s"])
        self.write_bundle(self.workstations, "dup", ["w"])
        self.assertEqual(
            bundle_apps._locate("dup"),
            self.servers / "dup" / "inventory.yml",
        )

    def test_missing_returns_none(self):
        self.assertIsNone(bundle_apps._locate("ghost"))


class TestResolve(_BundleFsMixin, unittest.TestCase):
    def test_returns_apps_in_declaration_order(self):
        self.write_bundle(self.servers, "edu", ["app_b", "app_a", "app_c"])
        self.assertEqual(
            bundle_apps.resolve(["edu"]),
            ["app_b", "app_a", "app_c"],
        )

    def test_deduplicates_across_bundles(self):
        self.write_bundle(self.servers, "one", ["shared", "uniq1"])
        self.write_bundle(self.workstations, "two", ["uniq2", "shared"])
        self.assertEqual(
            bundle_apps.resolve(["one", "two"]),
            ["shared", "uniq1", "uniq2"],
        )

    def test_missing_bundle_raises(self):
        self.write_bundle(self.servers, "present", ["a"])
        with self.assertRaises(FileNotFoundError) as ctx:
            bundle_apps.resolve(["present", "absent"])
        self.assertIn("absent", str(ctx.exception))
        self.assertNotIn("present", str(ctx.exception))

    def test_multiple_missing_listed(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            bundle_apps.resolve(["x", "y"])
        msg = str(ctx.exception)
        self.assertIn("x", msg)
        self.assertIn("y", msg)

    def test_empty_children_yields_empty_list(self):
        path = self.servers / "empty" / "inventory.yml"
        path.parent.mkdir()
        path.write_text("all:\n  children: {}\n", encoding="utf-8")
        self.assertEqual(bundle_apps.resolve(["empty"]), [])

    def test_missing_all_key_tolerated(self):
        path = self.servers / "weird" / "inventory.yml"
        path.parent.mkdir()
        path.write_text("other: 1\n", encoding="utf-8")
        self.assertEqual(bundle_apps.resolve(["weird"]), [])

    def test_null_children_tolerated(self):
        path = self.servers / "nullkids" / "inventory.yml"
        path.parent.mkdir()
        path.write_text("all:\n  children: ~\n", encoding="utf-8")
        self.assertEqual(bundle_apps.resolve(["nullkids"]), [])


class TestMain(_BundleFsMixin, unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with patch("sys.stdout", out), patch("sys.stderr", err):
            code = bundle_apps.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_success_prints_csv(self):
        self.write_bundle(self.servers, "edu", ["nextcloud", "openwebui"])
        code, out, err = self._run(["edu"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "nextcloud,openwebui\n")
        self.assertEqual(err, "")

    def test_multiple_bundles_csv_arg(self):
        self.write_bundle(self.servers, "a", ["x"])
        self.write_bundle(self.workstations, "b", ["y"])
        code, out, _ = self._run(["a,b"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "x,y\n")

    def test_blank_arg_returns_2(self):
        code, _, err = self._run([" , "])
        self.assertEqual(code, 2)
        self.assertIn("no bundle names", err)

    def test_missing_bundle_returns_2(self):
        code, _, err = self._run(["ghost"])
        self.assertEqual(code, 2)
        self.assertIn("ghost", err)

    def test_no_apps_resolved_returns_2(self):
        path = self.servers / "empty" / "inventory.yml"
        path.parent.mkdir()
        path.write_text("all:\n  children: {}\n", encoding="utf-8")
        code, _, err = self._run(["empty"])
        self.assertEqual(code, 2)
        self.assertIn("no role groups", err)


if __name__ == "__main__":
    unittest.main()
