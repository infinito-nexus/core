import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

import cli.meta.applications.resolution.run_after.__main__ as run_after_resolution


class TestRunAfterResolution(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

        self.repo_root = Path(self.tmpdir)
        self.roles_dir = self.repo_root / "roles"
        self.roles_dir.mkdir(parents=True, exist_ok=True)

        # Patch roles_dir() to point to our temp repo
        self._orig_roles_dir = run_after_resolution.roles_dir
        run_after_resolution.roles_dir = lambda: self.roles_dir  # type: ignore[assignment]
        self.addCleanup(self._restore_patches)

    def _restore_patches(self):
        run_after_resolution.roles_dir = self._orig_roles_dir  # type: ignore[assignment]

    def _make_role(self, name: str, run_after=None, with_meta: bool = True):
        """Create ``roles/<name>/meta/services.yml`` with the role's
        ``run_after`` on its primary entity (per req-010).

        If ``with_meta=False``, the role dir exists but ``meta/services.yml``
        does not.
        """
        role_path = self.roles_dir / name
        meta_dir = role_path / "meta"
        meta_dir.mkdir(parents=True, exist_ok=True)

        services_file = meta_dir / "services.yml"

        if not with_meta:
            if services_file.exists():
                services_file.unlink()
            return

        primary_entry: dict = {}
        if run_after is not None:
            primary_entry["run_after"] = run_after

        services_file.write_text(
            yaml.safe_dump({name: primary_entry}, sort_keys=False),
            encoding="utf-8",
        )

    def test_missing_meta_is_empty(self):
        self._make_role("A", with_meta=False)
        resolved = run_after_resolution.resolve_run_after_transitively("A")
        self.assertEqual(resolved, [])

    def test_direct_run_after(self):
        self._make_role("A", run_after=["B"])
        self._make_role("B", run_after=[])

        resolved = run_after_resolution.resolve_run_after_transitively("A")
        self.assertEqual(resolved, ["B"])

    def test_transitive_run_after_topological_order(self):
        # A -> [B, C], B -> [D], C -> [D]
        self._make_role("A", run_after=["B", "C"])
        self._make_role("B", run_after=["D"])
        self._make_role("C", run_after=["D"])
        self._make_role("D", run_after=[])

        resolved = run_after_resolution.resolve_run_after_transitively("A")

        # Must contain exactly B,C,D (no A)
        self.assertEqual(set(resolved), {"B", "C", "D"})
        self.assertNotIn("A", resolved)

        # D must be before B and C (prerequisite-first)
        self.assertLess(resolved.index("D"), resolved.index("B"))
        self.assertLess(resolved.index("D"), resolved.index("C"))

    def test_unknown_start_role_raises(self):
        with self.assertRaises(run_after_resolution.RunAfterResolutionError):
            run_after_resolution.resolve_run_after_transitively("DOES_NOT_EXIST")

    def test_invalid_reference_raises(self):
        self._make_role("A", run_after=["B"])
        # do not create role B
        with self.assertRaises(run_after_resolution.RunAfterResolutionError) as ctx:
            run_after_resolution.resolve_run_after_transitively("A")
        self.assertIn("Invalid run_after reference", str(ctx.exception))

    def test_cycle_raises(self):
        # A -> B -> C -> A
        self._make_role("A", run_after=["B"])
        self._make_role("B", run_after=["C"])
        self._make_role("C", run_after=["A"])

        with self.assertRaises(run_after_resolution.RunAfterResolutionError) as ctx:
            run_after_resolution.resolve_run_after_transitively("A")

        msg = str(ctx.exception)
        self.assertIn("Circular run_after dependency detected", msg)
        self.assertIn("A", msg)
        self.assertIn("B", msg)
        self.assertIn("C", msg)

    def test_invalid_run_after_type_raises(self):
        self._make_role("A", run_after=123)  # not a list

        with self.assertRaises(run_after_resolution.RunAfterResolutionError) as ctx:
            run_after_resolution.resolve_run_after_transitively("A")
        self.assertIn("Invalid run_after type", str(ctx.exception))

    def test_invalid_run_after_entry_raises(self):
        self._make_role("A", run_after=["B", {"role": "C"}])
        self._make_role("B", run_after=[])

        with self.assertRaises(run_after_resolution.RunAfterResolutionError) as ctx:
            run_after_resolution.resolve_run_after_transitively("A")
        self.assertIn("Invalid run_after entry", str(ctx.exception))

    def test_cli_output_whitespace_separated(self):
        self._make_role("A", run_after=["B", "C"])
        self._make_role("B", run_after=["D"])
        self._make_role("C", run_after=[])
        self._make_role("D", run_after=[])

        # Patch argv for argparse in main()
        orig_argv = os.sys.argv[:]
        try:
            os.sys.argv = ["prog", "A"]
            buf = io.StringIO()
            with redirect_stdout(buf):
                run_after_resolution.main()
            out = buf.getvalue().strip()
        finally:
            os.sys.argv = orig_argv

        parts = out.split()
        self.assertEqual(set(parts), {"B", "C", "D"})
        self.assertEqual(" ".join(parts), out)


if __name__ == "__main__":
    unittest.main()
