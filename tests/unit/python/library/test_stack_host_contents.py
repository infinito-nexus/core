from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.testing import patch_module_args
from ansible.modules import copy as copy_module

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "stack_host_contents.py"
ROLES = PROJECT_ROOT / "roles"
TODAY_TEMPLATES = (
    ROLES / "sys-front-tls" / "templates" / "http.conf.j2",
    ROLES / "sys-front-inj-all" / "templates" / "body_filter.lua.j2",
    *sorted((ROLES / "sys-svc-proxy" / "templates" / "vhost").glob("*.conf.j2")),
    *sorted(ROLES.glob("*/templates/proxy.conf.j2")),
)


def _load_stack_host_contents() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_stack_host_contents", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_stack_host_contents()


class WriteFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "redirect.conf"

    def tearDown(self):
        self._tmp.cleanup()

    def _module(self, *, check_mode=False):
        args = {
            "files": [],
            "mode": "0644",
            "diff_paths": [],
            "_ansible_check_mode": check_mode,
        }
        with patch_module_args(args):
            return AnsibleModule(
                argument_spec=_MOD.ARGUMENT_SPEC, supports_check_mode=True
            )

    def _write(self, content, *, check_mode=False):
        return _MOD.write_file(
            self._module(check_mode=check_mode), str(self.path), content, "0644"
        )

    def _mode(self):
        return stat.S_IMODE(self.path.stat().st_mode)

    def _content(self):
        return self.path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read the file under test changes between reads

    def test_creates_missing_file_with_mode(self):
        self.assertTrue(self._write("server {}\n"))
        self.assertEqual(self._content(), "server {}\n")
        self.assertEqual(self._mode(), 0o644)

    def test_unchanged_content_reports_no_change(self):
        self._write("server {}\n")
        self.assertFalse(self._write("server {}\n"))

    def test_replaces_differing_content(self):
        self._write("server {}\n")
        self.assertTrue(self._write("server { listen 80; }\n"))
        self.assertEqual(self._content(), "server { listen 80; }\n")

    def test_repairs_mode_drift(self):
        self._write("server {}\n")
        self.path.chmod(0o600)
        self.assertTrue(self._write("server {}\n"))
        self.assertEqual(self._mode(), 0o644)

    def test_check_mode_reports_without_writing(self):
        self.assertTrue(self._write("server {}\n", check_mode=True))
        self.assertFalse(self.path.exists())
        self._write("server {}\n")
        self.assertTrue(self._write("other\n", check_mode=True))
        self.assertEqual(self._content(), "server {}\n")

    def test_leaves_no_staging_file_behind(self):
        self._write("server {}\n")
        self._write("other\n")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])

    def _bytes(self):
        return self.path.read_bytes()  # nocheck: cache-read rewritten between reads

    def test_carriage_returns_are_stable_on_the_second_run(self):
        content = "a\r\nb\rc\n"
        self.assertTrue(self._write(content))
        self.assertEqual(self._bytes(), content.encode("utf-8"))
        self.assertFalse(self._write(content))

    def test_a_text_read_turns_carriage_returns_into_a_change(self):
        self._write("a\r\nb\n")
        self.assertNotEqual(self._content(), "a\r\nb\n")

    def test_a_non_utf8_file_is_replaced_without_a_crash(self):
        self.path.write_bytes(b"\xff\xfe\xe4 latin-1\n")
        with self.assertRaises(UnicodeDecodeError):
            self._content()
        self.assertTrue(self._write("server {}\n"))
        self.assertEqual(self._bytes(), b"server {}\n")
        self.assertFalse(self._write("server {}\n"))

    def test_todays_templates_written_as_text_stay_unchanged(self):
        self.assertGreater(len(TODAY_TEMPLATES), 20)
        for source in TODAY_TEMPLATES:
            content = read_text(str(source))
            with self.subTest(template=str(source.relative_to(PROJECT_ROOT))):
                self.path.write_text(content, encoding="utf-8")
                self.assertEqual(self._content(), content)
                self.assertFalse(self._write(content))


def _run_module(main, args: dict) -> dict:
    output = io.StringIO()
    with (
        patch_module_args(args),
        contextlib.redirect_stdout(output),
        contextlib.suppress(SystemExit),
    ):
        main()
    return json.loads(output.getvalue())


def _run_main(args: dict) -> dict:
    return _run_module(_MOD.main, args)


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.lua = self.root / "body.lua"
        self.vhost = self.root / "vhost.conf"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, lua: str, vhost: str, *, diff=True, check=False) -> dict:
        return _run_main(
            {
                "files": [
                    {"path": str(self.lua), "content": lua},
                    {"path": str(self.vhost), "content": vhost},
                ],
                "mode": "0644",
                "diff_paths": [str(self.lua)],
                "_ansible_diff": diff,
                "_ansible_check_mode": check,
            }
        )

    def test_a_lua_only_change_is_changed_and_names_only_the_lua(self):
        self._run("a\n", "v\n")
        result = self._run("b\n", "v\n")
        self.assertTrue(result["changed"])
        self.assertEqual(result["changed_paths"], [str(self.lua)])

    def test_an_unchanged_run_reports_ok(self):
        self._run("a\n", "v\n")
        result = self._run("a\n", "v\n")
        self.assertFalse(result["changed"])
        self.assertEqual(result["changed_paths"], [])
        self.assertEqual(result["diff"], [])

    def test_diff_mode_reports_only_the_listed_path(self):
        self._run("a\n", "v\n")
        result = self._run("b\n", "secret\n")
        self.assertEqual(
            result["diff"],
            [
                {
                    "before_header": str(self.lua),
                    "after_header": str(self.lua),
                    "before": "a\n",
                    "after": "b\n",
                }
            ],
        )

    def test_a_new_file_diffs_from_empty(self):
        result = self._run("a\n", "v\n")
        self.assertEqual(result["diff"][0]["before"], "")
        self.assertEqual(result["diff"][0]["after"], "a\n")

    def test_without_diff_mode_no_content_leaves_the_module(self):
        self._run("a\n", "v\n", diff=False)
        result = self._run("b\n", "w\n", diff=False)
        self.assertTrue(result["changed"])
        self.assertEqual(result["diff"], [])

    def test_check_mode_diffs_without_writing(self):
        self._run("a\n", "v\n")
        result = self._run("b\n", "v\n", check=True)
        self.assertTrue(result["changed"])
        self.assertEqual(result["diff"][0]["after"], "b\n")
        self.assertEqual(
            self.lua.read_text(
                encoding="utf-8"
            ),  # nocheck: cache-read the file under test changes between reads
            "a\n",
        )

    def test_carriage_returns_neither_change_nor_diff_on_the_second_run(self):
        self._run("a\r\n", "v\r\n")
        result = self._run("a\r\n", "v\r\n")
        self.assertFalse(result["changed"])
        self.assertEqual(result["diff"], [])

    def test_a_non_utf8_file_diffs_with_replacement_characters(self):
        self.lua.write_bytes(b"old \xff\n")
        self.vhost.write_bytes(b"\xe4\n")
        result = self._run("new\n", "v\n")
        self.assertEqual(result["changed_paths"], [str(self.lua), str(self.vhost)])
        self.assertEqual(result["diff"][0]["before"], "old �\n")

    def test_the_diff_paths_argument_is_required(self):
        result = _run_main(
            {"files": [{"path": str(self.lua), "content": "a\n"}], "mode": "0644"}
        )
        self.assertTrue(result["failed"])
        self.assertIn("diff_paths", result["msg"])


class AttributeParityWithTheCopyModuleTests(unittest.TestCase):
    """The template action ends in the copy module; the fold ends in write_file."""

    CONTENT = 'ngx.arg[1] = whole or ""\n'

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.group = self._assignable_secondary_group()

    def _assignable_secondary_group(self) -> int:
        probe = self.root / "probe"
        probe.touch()
        for gid in os.getgroups():
            if gid == os.getegid():
                continue
            try:
                os.chown(probe, -1, gid)
            except OSError:
                continue
            return gid
        return os.getegid()

    def tearDown(self):
        self._tmp.cleanup()

    def _twin_dirs(self, name: str, *, setgid: bool) -> tuple[Path, Path]:
        dirs = (self.root / f"{name}-copy", self.root / f"{name}-fold")
        for directory in dirs:
            directory.mkdir()
            if setgid:
                os.chown(directory, -1, self.group)
                directory.chmod(0o2775)
        return dirs

    def _copy(self, dest: Path) -> None:
        staged = self.root / f"staged-{dest.parent.name}"
        staged.write_text(self.CONTENT, encoding="utf-8")
        result = _run_module(
            copy_module.main,
            {
                "src": str(staged),
                "dest": str(dest),
                "mode": "0644",
                "_original_basename": "body_filter.lua.j2",
            },
        )
        self.assertNotIn("failed", result, result)

    def _fold(self, dest: Path, mode: str = "0644") -> None:
        with patch_module_args({"files": [], "mode": mode, "diff_paths": []}):
            module = AnsibleModule(
                argument_spec=_MOD.ARGUMENT_SPEC, supports_check_mode=True
            )
        _MOD.write_file(module, str(dest), self.CONTENT, mode)

    @staticmethod
    def _attributes(path: Path) -> tuple:
        info = path.stat()
        return (
            info.st_uid,
            info.st_gid,
            stat.S_IMODE(info.st_mode),
            path.read_bytes(),  # nocheck: cache-read the file under test changes between reads
        )

    def _assert_parity(self, name: str, *, setgid=False, existing=None) -> None:
        copy_dir, fold_dir = self._twin_dirs(name, setgid=setgid)
        for directory in (copy_dir, fold_dir):
            if existing is not None:
                content, mode, group = existing
                target = directory / "body.lua"
                target.write_text(content, encoding="utf-8")
                os.chown(target, -1, group)
                target.chmod(mode)
        self._copy(copy_dir / "body.lua")
        self._fold(fold_dir / "body.lua")
        self.assertEqual(
            self._attributes(fold_dir / "body.lua"),
            self._attributes(copy_dir / "body.lua"),
        )

    def test_a_new_file(self):
        self._assert_parity("new")

    def test_a_new_file_in_a_setgid_directory(self):
        self._assert_parity("setgid", setgid=True)

    def test_a_changed_file_keeps_its_group_and_gets_the_mode(self):
        self._assert_parity("changed", existing=("old\n", 0o600, self.group))

    def test_an_unchanged_file_only_gets_the_mode(self):
        self._assert_parity("unchanged", existing=(self.CONTENT, 0o600, self.group))

    def test_a_mode_difference_is_detected(self):
        copy_dir, fold_dir = self._twin_dirs("control", setgid=False)
        self._copy(copy_dir / "body.lua")
        self._fold(fold_dir / "body.lua", mode="0600")
        self.assertNotEqual(
            self._attributes(fold_dir / "body.lua"),
            self._attributes(copy_dir / "body.lua"),
        )


if __name__ == "__main__":
    unittest.main()
