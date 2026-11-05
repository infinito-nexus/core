from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import patch

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.testing import patch_module_args
from ansible.modules import copy as copy_module
from ansible.modules import file as file_module

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from types import ModuleType

sys.path.insert(0, str(PROJECT_ROOT))

MODULE_PATH = PROJECT_ROOT / "library" / "copy_batch.py"


def _load_copy_batch() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "library_copy_batch", str(MODULE_PATH)
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load: {MODULE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_MOD = _load_copy_batch()


def _sha1(data):
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()


def _umask():
    current = os.umask(0)
    os.umask(current)
    return current


def _call(main, args):
    buffer = io.StringIO()
    with (
        patch_module_args(args),
        contextlib.redirect_stdout(buffer),
        contextlib.suppress(SystemExit),
    ):
        main()
    return json.loads(buffer.getvalue())


class _Tree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.dest = self.root / "dest"
        self.dest.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.archive = self.root / "archive.tar"

    def tearDown(self):
        self._tmp.cleanup()

    def _pack(self, files, *, names=None, kinds=None):
        with tarfile.open(self.archive, "w") as bundle:
            for name, data in files.items():
                member = tarfile.TarInfo((names or {}).get(name, name))
                member.type = (kinds or {}).get(name, tarfile.REGTYPE)
                member.size = len(data) if member.isreg() else 0
                bundle.addfile(member, io.BytesIO(data) if member.isreg() else None)
        return {name: _sha1(data) for name, data in files.items()}

    def _run(
        self,
        files,
        *,
        settled=(),
        directories=(),
        mode="0644",
        directory_mode=None,
        digests=None,
        names=None,
        kinds=None,
        tree=None,
    ):
        packed = self._pack(files, names=names, kinds=kinds)
        listed = packed if digests is None else digests
        return _call(
            _MOD.main,
            {
                "src": str(self.archive),
                "dest": f"{self.dest}/",
                "files": [
                    {"path": name, "checksum": digest}
                    for name, digest in listed.items()
                ],
                "settled": list(settled),
                "directories": list(directories),
                "tree": [*listed, *settled, *directories] if tree is None else tree,
                "mode": mode,
                "directory_mode": directory_mode,
                "_ansible_tmpdir": str(self.work),
            },
        )

    def _write(self, rel, data, mode):
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    @staticmethod
    def _mode(path):
        return stat.S_IMODE(path.lstat().st_mode)

    @staticmethod
    def _bytes(path):
        return path.read_bytes()  # nocheck: cache-read


class TestWrites(_Tree):
    def test_replaces_and_creates_files_with_mode(self):
        self._write("icon.png", b"old", 0o600)

        result = self._run({"icon.png": b"new", "nested/icon.svg": b"<svg/>"})

        self.assertTrue(result["changed"])
        self.assertNotIn("refused", result)
        self.assertEqual(self._bytes(self.dest / "icon.png"), b"new")
        self.assertEqual(self._bytes(self.dest / "nested/icon.svg"), b"<svg/>")
        self.assertEqual(self._mode(self.dest / "icon.png"), 0o644)
        self.assertEqual(self._mode(self.dest / "nested/icon.svg"), 0o644)

    def test_created_parents_receive_the_directory_mode(self):
        self._run({"a/b/icon.svg": b"<svg/>"}, directory_mode="0750")

        self.assertEqual(self._mode(self.dest / "a"), 0o750)
        self.assertEqual(self._mode(self.dest / "a/b"), 0o750)

    def test_existing_parent_keeps_its_mode(self):
        (self.dest / "a").mkdir()
        (self.dest / "a").chmod(0o701)

        self._run({"a/b/icon.svg": b"<svg/>"}, directory_mode="0750")

        self.assertEqual(self._mode(self.dest / "a"), 0o701)
        self.assertEqual(self._mode(self.dest / "a/b"), 0o750)

    def test_unset_directory_mode_keeps_the_umask_mode(self):
        self._run({"a/icon.svg": b"<svg/>"}, directory_mode=None)

        self.assertEqual(self._mode(self.dest / "a"), 0o777 & ~_umask())

    def test_existing_leaf_directory_receives_the_directory_mode(self):
        (self.dest / "leaf").mkdir()
        (self.dest / "leaf").chmod(0o700)

        result = self._run({}, directories=["leaf"], directory_mode="0750")

        self.assertTrue(result["changed"])
        self.assertEqual(self._mode(self.dest / "leaf"), 0o750)

    def test_missing_leaf_directory_is_created_with_its_parents(self):
        result = self._run({}, directories=["a/leaf"], directory_mode="0750")

        self.assertTrue(result["changed"])
        self.assertEqual(self._mode(self.dest / "a"), 0o750)
        self.assertEqual(self._mode(self.dest / "a/leaf"), 0o750)

    def test_settled_file_keeps_its_content_and_inode(self):
        path = self._write("icon.png", b"png", 0o600)
        inode = path.stat().st_ino

        result = self._run({}, settled=["icon.png"])

        self.assertTrue(result["changed"])
        self.assertEqual(path.stat().st_ino, inode)
        self.assertEqual(self._bytes(path), b"png")
        self.assertEqual(self._mode(path), 0o644)

    def test_settled_file_with_its_mode_reports_no_change(self):
        self._write("icon.png", b"png", 0o644)

        result = self._run({}, settled=["icon.png"])

        self.assertFalse(result["changed"])

    def test_replaced_file_gets_the_owner_of_the_file_it_replaces(self):
        path = self._write("icon.png", b"old", 0o600)
        owner = (path.stat().st_uid, path.stat().st_gid)

        with (
            patch.object(
                AnsibleModule,
                "atomic_move",
                autospec=True,
                side_effect=AnsibleModule.atomic_move,
            ) as move,
            patch("os.chown", wraps=os.chown) as chown,
        ):
            self._run({"icon.png": b"new"})

        self.assertEqual(move.call_args.args[2], str(path))
        self.assertNotIn("keep_dest_attrs", move.call_args.kwargs)
        self.assertIn(owner, [call.args[1:] for call in chown.call_args_list])
        self.assertEqual((path.stat().st_uid, path.stat().st_gid), owner)

    def test_files_outside_the_call_stay(self):
        other = self._write("other.png", b"other", 0o600)

        self._run({"icon.png": b"new"})

        self.assertEqual(self._bytes(other), b"other")
        self.assertEqual(self._mode(other), 0o600)

    def test_symlinked_parent_directory_is_written_through(self):
        real = self.root / "real"
        real.mkdir()
        (self.dest / "linked").symlink_to(real)

        result = self._run({"linked/icon.svg": b"<svg/>"})

        self.assertTrue(result["changed"])
        self.assertEqual(self._bytes(real / "icon.svg"), b"<svg/>")

    def test_staged_copies_leave_no_trace(self):
        self._run({"icon.png": b"new", "nested/icon.svg": b"<svg/>"})

        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(
            sorted(p.name for p in self.dest.iterdir()), ["icon.png", "nested"]
        )


class TestRefusals(_Tree):
    def _assert_refused(self, result, path):
        self.assertFalse(result["changed"])
        self.assertTrue(any(str(path) in reason for reason in result["refused"]))
        self.assertFalse((self.dest / "fresh.png").exists())

    def test_symlink_in_place_of_a_file_is_refused_and_kept(self):
        target = self.root / "target.png"
        target.write_bytes(b"target")
        (self.dest / "icon.png").symlink_to(target)

        result = self._run({"icon.png": b"new", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "icon.png")
        self.assertTrue((self.dest / "icon.png").is_symlink())
        self.assertEqual(self._bytes(target), b"target")

    def test_dangling_symlink_in_place_of_a_file_is_refused(self):
        (self.dest / "icon.png").symlink_to(self.root / "absent")

        result = self._run({"icon.png": b"new", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "icon.png")

    def test_directory_in_place_of_a_file_is_refused(self):
        (self.dest / "icon.png").mkdir()

        result = self._run({"icon.png": b"new", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "icon.png")
        self.assertTrue((self.dest / "icon.png").is_dir())

    def test_fifo_in_place_of_a_file_is_refused(self):
        os.mkfifo(self.dest / "icon.png")

        result = self._run({"icon.png": b"new", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "icon.png")

    def test_file_in_place_of_a_parent_directory_is_refused(self):
        self._write("nested", b"file", 0o644)

        result = self._run({"nested/icon.svg": b"<svg/>", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "nested")
        self.assertEqual(self._bytes(self.dest / "nested"), b"file")

    def test_dangling_symlink_in_place_of_a_parent_directory_is_refused(self):
        (self.dest / "nested").symlink_to(self.root / "absent")

        result = self._run({"nested/a/icon.svg": b"<svg/>", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "nested")
        self.assertFalse((self.root / "absent").exists())

    def test_symlink_in_place_of_a_leaf_directory_is_refused(self):
        (self.root / "real").mkdir()
        (self.dest / "leaf").symlink_to(self.root / "real")

        result = self._run(
            {"fresh.png": b"fresh"}, directories=["leaf"], directory_mode="0750"
        )

        self._assert_refused(result, self.dest / "leaf")
        self.assertNotEqual(self._mode(self.root / "real"), 0o750)

    def test_file_in_place_of_a_leaf_directory_is_refused(self):
        self._write("leaf", b"", 0o644)

        result = self._run({"fresh.png": b"fresh"}, directories=["leaf"])

        self._assert_refused(result, self.dest / "leaf")

    def test_symlink_loop_in_place_of_a_parent_directory_is_refused(self):
        (self.dest / "loop").symlink_to(self.dest / "loop")

        result = self._run({"loop/icon.svg": b"<svg/>", "fresh.png": b"fresh"})

        self._assert_refused(result, self.dest / "loop")

    def test_missing_settled_file_is_refused(self):
        result = self._run({"fresh.png": b"fresh"}, settled=["icon.png"])

        self._assert_refused(result, self.dest / "icon.png")


class TestFailures(_Tree):
    def _assert_failed(self, result, needle):
        self.assertTrue(result["failed"])
        self.assertIn(needle, result["msg"])
        self.assertFalse((self.dest / "icon.png").exists())

    def test_checksum_mismatch_fails_naming_the_file_and_writes_nothing(self):
        digests = {"icon.png": _sha1(b"new"), "nested/icon.svg": _sha1(b"other")}

        result = self._run(
            {"icon.png": b"new", "nested/icon.svg": b"<svg/>"}, digests=digests
        )

        self._assert_failed(result, "nested/icon.svg")
        self.assertFalse((self.dest / "nested").exists())

    def test_parent_reference_member_fails(self):
        result = self._run(
            {"icon.png": b"new", "evil": b"x"},
            names={"evil": "../evil"},
            digests={"icon.png": _sha1(b"new")},
        )

        self._assert_failed(result, "../evil")
        self.assertFalse((self.root / "evil").exists())

    def test_absolute_member_fails(self):
        result = self._run(
            {"icon.png": b"new", "evil": b"x"},
            names={"evil": f"{self.root}/evil"},
            digests={"icon.png": _sha1(b"new")},
        )

        self._assert_failed(result, "leaves the destination")
        self.assertFalse((self.root / "evil").exists())

    def test_unexpected_member_fails(self):
        result = self._run(
            {"icon.png": b"new", "extra.png": b"x"},
            digests={"icon.png": _sha1(b"new")},
        )

        self._assert_failed(result, "extra.png")

    def test_missing_member_fails(self):
        result = self._run(
            {"icon.png": b"new"},
            digests={"icon.png": _sha1(b"new"), "gone.png": _sha1(b"x")},
        )

        self._assert_failed(result, "gone.png")

    def test_link_member_fails(self):
        result = self._run(
            {"icon.png": b"new", "link.png": b""},
            kinds={"link.png": tarfile.SYMTYPE},
        )

        self._assert_failed(result, "not a regular file")

    def test_parent_reference_in_the_arguments_fails(self):
        result = self._run({}, directories=["../outside"])

        self.assertTrue(result["failed"])
        self.assertIn("../outside", result["msg"])
        self.assertFalse((self.root / "outside").exists())

    def test_write_failure_names_the_file_and_fails(self):
        original = AnsibleModule.atomic_move

        def move(module, src, dest, **kwargs):
            if dest.endswith("nested/icon.svg"):
                raise Exception("Could not replace")  # noqa: TRY002 - atomic_move raises a bare Exception
            return original(module, src, dest, **kwargs)

        with patch.object(
            AnsibleModule, "atomic_move", autospec=True, side_effect=move
        ):
            result = self._run({"icon.png": b"new", "nested/icon.svg": b"<svg/>"})

        self.assertTrue(result["failed"])
        self.assertIn(str(self.dest / "nested/icon.svg"), result["msg"])
        self.assertTrue(result["changed"])

    def test_failure_after_creating_a_parent_reports_the_change(self):
        with patch.object(
            AnsibleModule,
            "atomic_move",
            autospec=True,
            side_effect=Exception("Could not replace"),
        ):
            result = self._run({"nested/icon.svg": b"<svg/>"})

        self.assertTrue(result["failed"])
        self.assertTrue(result["changed"])
        self.assertTrue((self.dest / "nested").is_dir())

    def test_repeated_file_path_fails(self):
        result = self._run(
            {"fresh.png": b"fresh"},
            digests={"fresh.png": _sha1(b"fresh")},
            tree=["fresh.png"],
        )
        self.assertNotIn("failed", result)

        repeated = _call(
            _MOD.main,
            {
                "src": str(self.archive),
                "dest": f"{self.dest}/",
                "files": [
                    {"path": "fresh.png", "checksum": _sha1(b"fresh")},
                    {"path": "fresh.png", "checksum": _sha1(b"fresh")},
                ],
                "settled": [],
                "directories": [],
                "tree": ["fresh.png"],
                "mode": "0644",
                "directory_mode": None,
                "_ansible_tmpdir": str(self.work),
            },
        )

        self.assertTrue(repeated["failed"])
        self.assertIn("repeat", repeated["msg"])


class TestOrderAndAliases(_Tree):
    def test_files_are_written_in_the_given_order(self):
        order = ["b/z.png", "a.png", "c.png"]

        with patch.object(
            AnsibleModule,
            "atomic_move",
            autospec=True,
            side_effect=AnsibleModule.atomic_move,
        ) as move:
            self._run({name: name.encode() for name in order})

        self.assertEqual(
            [call.args[2] for call in move.call_args_list],
            [str(self.dest / name) for name in order],
        )

    def test_settled_files_are_handled_in_tree_order(self):
        settled = self._write("s.png", b"s", 0o600)

        with patch.object(
            AnsibleModule,
            "atomic_move",
            autospec=True,
            side_effect=Exception("Could not replace"),
        ):
            result = self._run(
                {"b.png": b"b"}, settled=["s.png"], tree=["s.png", "b.png"]
            )

        self.assertTrue(result["failed"])
        self.assertEqual(self._mode(settled), 0o644)

    def test_settled_file_after_a_failed_write_stays_untouched(self):
        settled = self._write("s.png", b"s", 0o600)

        with patch.object(
            AnsibleModule,
            "atomic_move",
            autospec=True,
            side_effect=Exception("Could not replace"),
        ):
            result = self._run(
                {"b.png": b"b"}, settled=["s.png"], tree=["b.png", "s.png"]
            )

        self.assertTrue(result["failed"])
        self.assertEqual(self._mode(settled), 0o600)

    def test_path_missing_from_tree_fails(self):
        result = self._run({"b.png": b"b"}, tree=[])

        self.assertTrue(result["failed"])
        self.assertIn("missing from tree", result["msg"])

    def test_two_paths_through_a_symlinked_directory_are_refused(self):
        (self.dest / "y").mkdir()
        self._write("y/f.js", b"y", 0o644)
        (self.dest / "x").symlink_to(self.dest / "y")

        result = self._run(
            {"x/f.js": b"x", "fresh.png": b"fresh"},
            tree=["x/f.js", "y/f.js", "fresh.png"],
        )

        self.assertFalse(result["changed"])
        self.assertIn("reach the same entry", " ".join(result["refused"]))
        self.assertEqual(self._bytes(self.dest / "y/f.js"), b"y")
        self.assertFalse((self.dest / "fresh.png").exists())

    def test_two_missing_paths_through_a_symlinked_directory_are_refused(self):
        (self.dest / "y").mkdir()
        (self.dest / "x").symlink_to(self.dest / "y")

        result = self._run({"x/f.js": b"x", "y/f.js": b"y"}, tree=["x/f.js", "y/f.js"])

        self.assertIn("reach the same entry", " ".join(result["refused"]))
        self.assertFalse((self.dest / "y/f.js").exists())

    def test_hard_linked_targets_are_refused(self):
        first = self._write("a.png", b"same", 0o644)
        (self.dest / "b.png").hardlink_to(first)

        result = self._run({"a.png": b"new"}, tree=["a.png", "b.png"])

        self.assertIn("reach the same entry", " ".join(result["refused"]))
        self.assertEqual(self._bytes(self.dest / "b.png"), b"same")

    def test_unsafe_writes_reaches_atomic_move_from_the_environment(self):
        with (
            patch.dict(os.environ, {"ANSIBLE_UNSAFE_WRITES": "1"}),
            patch.object(
                AnsibleModule,
                "atomic_move",
                autospec=True,
                side_effect=AnsibleModule.atomic_move,
            ) as move,
        ):
            self._run({"icon.png": b"new"})

        self.assertTrue(move.call_args.kwargs["unsafe_writes"])

    def test_leaf_created_concurrently_is_accepted(self):
        original = Path.mkdir

        def racing(path, *args, **kwargs):
            original(path, *args, **kwargs)
            raise FileExistsError(path)

        with patch.object(Path, "mkdir", autospec=True, side_effect=racing):
            result = self._run({}, directories=["leaf"], directory_mode="0750")

        self.assertTrue(result["changed"])
        self.assertEqual(self._mode(self.dest / "leaf"), 0o750)


class TestSameEndStateAsTheCopyModule(unittest.TestCase):
    MODE = "0644"
    DIRECTORY_MODE = "0750"
    CONTENT: ClassVar[dict[str, bytes]] = {
        "replaced.png": b"new",
        "fresh/deep/new.svg": b"<svg/>",
        "kept-dir/new.png": b"png",
    }
    SETTLED: ClassVar[tuple[str, ...]] = ("mode-drift.png",)
    LEAVES: ClassVar[tuple[str, ...]] = ("existing-leaf", "absent/leaf")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, dest):
        dest.mkdir()
        (dest / "replaced.png").write_bytes(b"old")
        (dest / "replaced.png").chmod(0o600)
        (dest / "mode-drift.png").write_bytes(b"same")
        (dest / "mode-drift.png").chmod(0o600)
        (dest / "kept-dir").mkdir()
        (dest / "kept-dir").chmod(0o701)
        (dest / "existing-leaf").mkdir()
        (dest / "existing-leaf").chmod(0o700)
        (dest / "untouched.png").write_bytes(b"untouched")

    def _regular_copy(self, dest):
        staging = self.root / "staging"
        staging.mkdir()
        for rel, data in self.CONTENT.items():
            source = staging / ".source"
            source.write_bytes(data)
            result = _call(
                copy_module.main,
                {
                    "src": str(source),
                    "dest": f"{dest}/",
                    "mode": self.MODE,
                    "directory_mode": self.DIRECTORY_MODE,
                    "_original_basename": rel,
                    "follow": False,
                    "checksum": _sha1(data),
                },
            )
            self.assertNotIn("failed", result, result)
        for rel in self.SETTLED:
            result = _call(
                file_module.main,
                {
                    "mode": self.MODE,
                    "dest": f"{dest}/",
                    "_original_basename": rel,
                    "recurse": False,
                    "state": "file",
                },
            )
            self.assertNotIn("failed", result, result)
        for rel in self.LEAVES:
            result = _call(
                file_module.main,
                {
                    "path": str(dest / rel),
                    "state": "directory",
                    "mode": self.DIRECTORY_MODE,
                    "recurse": False,
                },
            )
            self.assertNotIn("failed", result, result)

    def _batch(self, dest):
        archive = self.root / "archive.tar"
        work = self.root / "work"
        work.mkdir()
        with tarfile.open(archive, "w") as bundle:
            for rel, data in self.CONTENT.items():
                member = tarfile.TarInfo(rel)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
        result = _call(
            _MOD.main,
            {
                "src": str(archive),
                "dest": f"{dest}/",
                "files": [
                    {"path": rel, "checksum": _sha1(data)}
                    for rel, data in self.CONTENT.items()
                ],
                "settled": list(self.SETTLED),
                "directories": list(self.LEAVES),
                "tree": [*self.CONTENT, *self.SETTLED, *self.LEAVES],
                "mode": self.MODE,
                "directory_mode": self.DIRECTORY_MODE,
                "_ansible_tmpdir": str(work),
            },
        )
        self.assertTrue(result["changed"], result)

    @staticmethod
    def _snapshot(dest):
        entries = {}
        for path in sorted(dest.rglob("*")):  # nocheck: project-walk
            info = path.lstat()
            content = None
            if path.is_file():
                content = path.read_bytes()  # nocheck: cache-read
            entries[str(path.relative_to(dest))] = (
                stat.S_IFMT(info.st_mode),
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                info.st_gid,
                content,
            )
        return entries

    def test_batch_leaves_the_tree_the_regular_copy_leaves(self):
        regular, batch = self.root / "regular", self.root / "batch"
        self._seed(regular)
        self._seed(batch)

        self._regular_copy(regular)
        self._batch(batch)

        self.assertEqual(self._snapshot(batch), self._snapshot(regular))
        self.assertEqual(self._snapshot(batch)["kept-dir"][1], 0o701)
        self.assertEqual(self._snapshot(batch)["existing-leaf"][1], 0o750)


if __name__ == "__main__":
    unittest.main()
