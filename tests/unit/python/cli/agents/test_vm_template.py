from __future__ import annotations

import contextlib
import io
import os
import shutil
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from cli.agents import vm_template as cli
from utils.agents import vm_template
from utils.cache.files import read_text

SUM = "ab" * 32
FILLED_SPEC = read_text(str(vm_template.TEMPLATE_DIR / vm_template.SPEC_FILE)).replace(
    'sha256: ""', f'sha256: "{SUM}"'
)


def _tree(root: Path) -> list[Path]:
    walk = root.rglob("*")  # nocheck: project-walk  callers pass tempdir trees
    return sorted(p.relative_to(root) for p in walk)


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.template = self.tmp / "vm-template"
        shutil.copytree(vm_template.TEMPLATE_DIR, self.template)
        (self.template / vm_template.SPEC_FILE).write_text(
            FILLED_SPEC, encoding="utf-8"
        )
        patcher = mock.patch.object(vm_template, "TEMPLATE_DIR", self.template)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def _main(self, *argv: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(list(argv))
        return code, err.getvalue()

    def test_dry_run_prints_the_build(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(
                ["--kind", "proxmox", "--out", str(self.tmp / "new"), "--dry-run"]
            )
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith("mkosi "))
        self.assertIn(
            f"--extra-tree={self.tmp / 'new' / vm_template.ROOTFS}", out.getvalue()
        )

    def test_used_out_directory_stops_the_build(self):
        used = self.tmp / "used"
        used.mkdir()
        (used / "leftover").write_text("x", encoding="utf-8")
        code, err = self._main("--kind", "incus", "--out", str(used))
        self.assertEqual(code, 2)
        self.assertIn("already holds files", err)

    def test_render_project_writes_the_project_and_a_rootfs_copy(self):
        out = self.tmp / "out"
        cli.render_project(out)
        project = out / "project"
        self.assertTrue((project / "mkosi.conf").is_file())
        self.assertTrue((project / "metadata.yaml").is_file())
        self.assertTrue((project / "mkosi.finalize").stat().st_mode & 0o100)
        self.assertTrue((project / "mkosi.postinst.chroot").stat().st_mode & 0o100)
        self.assertEqual(
            _tree(self.template / vm_template.ROOTFS), _tree(out / vm_template.ROOTFS)
        )

    def test_hard_link_added_after_the_plan_stops_the_render(self):
        out = self.tmp / "out"
        vm_template.plan(
            "incus", self.template, vm_template.PROJECT_ROOT / "roles", out
        )
        victim = self.tmp / "victim"
        victim.write_text("secret", encoding="utf-8")
        os.link(victim, self.template / vm_template.ROOTFS / "late")
        with self.assertRaises(vm_template.VmTemplateError):
            cli.render_project(out)
        self.assertFalse((out / vm_template.ROOTFS).exists())

    def test_unfilled_sum_stops_the_build_before_mkosi(self):
        (self.template / vm_template.SPEC_FILE).write_text(
            FILLED_SPEC.replace(SUM, "", 1), encoding="utf-8"
        )
        with mock.patch.object(cli.subprocess, "run") as run:
            code, err = self._main("--kind", "incus", "--out", str(self.tmp / "out"))
        self.assertEqual(code, 2)
        self.assertIn("needs a sha256", err)
        run.assert_not_called()

    def test_render_project_refuses_a_used_directory(self):
        (self.tmp / "out" / "project").mkdir(parents=True)
        with self.assertRaises(ValueError):
            cli.render_project(self.tmp / "out")


if __name__ == "__main__":
    unittest.main()
