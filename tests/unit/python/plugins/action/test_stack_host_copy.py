import hashlib
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from ansible.plugins.action import copy as copy_action

from plugins.action.stack_host_copy import (
    ActionModule,
    _walk_dirs_without_bytecode_caches,
)


class _FakeTask:
    def __init__(self, *, args=None):
        self.args = {} if args is None else dict(args)
        self.async_val = 0
        self.check_mode = False
        self.diff = False
        self.no_log = False
        self.action = "stack_host_copy"

    def get_search_path(self):
        return []


class _FakeTemplar:
    def __init__(self, *, is_stack_host=True):
        self._is_stack_host = is_stack_host
        self.available_variables: dict[str, object] = {}

    def template(self, raw):
        return self._is_stack_host


def _make_action(task, templar):
    action = object.__new__(ActionModule)
    action._task = task
    action._templar = templar
    return action


class TestStackHostCopy(unittest.TestCase):
    def test_skips_silently_on_non_stack_host(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        action = _make_action(task, _FakeTemplar(is_stack_host=False))

        result = action.run(task_vars={})

        self.assertTrue(result["skipped"])
        self.assertFalse(result["changed"])
        self.assertIn("IS_STACK_HOST", result["skip_reason"])

    def test_skips_when_templar_returns_string_false(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        action = _make_action(task, _FakeTemplar(is_stack_host="False"))

        result = action.run(task_vars={})

        self.assertTrue(result["skipped"])

    def test_delegates_to_copy_on_stack_host(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ) as super_run:
            action.run(task_vars={})

        super_run.assert_called_once()

    def test_seeds_templar_with_task_vars_before_rendering(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        templar = _FakeTemplar(is_stack_host=True)
        action = _make_action(task, templar)

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={"IS_STACK_HOST": True, "ANSIBLE_VERSION": "9.0"})

        self.assertEqual(templar.available_variables.get("IS_STACK_HOST"), True)
        self.assertEqual(templar.available_variables.get("ANSIBLE_VERSION"), "9.0")

    def test_defaults_mode_to_0644_when_unset(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={})

        self.assertEqual(task.args["mode"], "0644")

    def test_keeps_caller_supplied_mode(self):
        task = _FakeTask(
            args={"src": "x", "dest": "/opt/compose/app/x", "mode": "0600"}
        )
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ):
            action.run(task_vars={})

        self.assertEqual(task.args["mode"], "0600")

    def test_file_source_never_takes_the_tree_check(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ) as super_run:
            result = action.run(task_vars={})

        super_run.assert_called_once()
        self.assertTrue(result["changed"])

    def test_is_stack_host_expr_carries_trust_tag(self):
        from ansible.template import is_trusted_as_template

        from plugins.action.stack_host_copy import _IS_STACK_HOST_EXPR

        self.assertTrue(
            is_trusted_as_template(_IS_STACK_HOST_EXPR),
            "The IS_STACK_HOST template expression must carry the TrustedAsTemplate "
            "tag; otherwise Ansible 2.19+ returns the literal string unchanged.",
        )


class _FakeShell:
    def __init__(self):
        self.tmpdir = None

    def join_path(self, *parts):
        return os.path.join(*parts)  # noqa: PTH118 - mirrors the sh shell plugin, whose join_path keeps a trailing slash

    def path_has_trailing_slash(self, path):
        return path.endswith("/")


class _FakeConnection:
    def __init__(self):
        self._shell = _FakeShell()
        self.become = None


class _FakeLoader:
    def get_real_file(self, path, decrypt=True):
        return path

    def cleanup_tmp_file(self, path):
        return None

    def path_dwim_relative_stack(self, paths, dirname, needle):
        return needle


class _FakePlayContext:
    no_log = False


def _sha1(data):
    return hashlib.sha1(data).hexdigest()  # noqa: S324 - the checksum Ansible copy compares is SHA-1


class _Dir:
    def __init__(self, mode):
        self.mode = mode


class _Link:
    def __init__(self, data):
        self.data = data


def _mode_bits(mode):
    return mode if isinstance(mode, int) else int(mode, 8)


class _FakeRemote:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.calls = []
        self.args = []
        self.transfers = []
        self.fixups = 0

    def transfer(self, local, remote_path):
        if not remote_path.endswith(".tar"):
            self.transfers.append(Path(local).read_bytes())  # nocheck: cache-read
            return remote_path
        with tarfile.open(local) as bundle:
            self.transfers.append(
                {
                    member.name: bundle.extractfile(member).read()
                    for member in bundle.getmembers()
                }
            )
        return remote_path

    def fixup(self, *args, **kwargs):
        self.fixups += 1

    def __call__(self, module_name=None, module_args=None, task_vars=None, **kwargs):
        self.calls.append(module_name)
        self.args.append(module_args)
        if module_name == "ansible.legacy.file_checksums":
            return {
                "changed": False,
                "states": {p: self._state(p) for p in module_args["paths"]},
            }
        if module_name == "ansible.legacy.copy_batch":
            return self._copy_batch(module_args)
        if module_name == "ansible.legacy.stat":
            entry = self.entries.get(module_args["path"])
            if entry is None:
                return {"stat": {"exists": False}}
            if isinstance(entry, _Dir):
                return {"stat": {"exists": True, "isdir": True}}
            if isinstance(entry, _Link):
                digest = _sha1(entry.data) if module_args["follow"] else ""
                return {
                    "stat": {
                        "exists": True,
                        "isdir": False,
                        "islnk": True,
                        "checksum": digest,
                    }
                }
            return {
                "stat": {
                    "exists": True,
                    "isdir": False,
                    "islnk": False,
                    "checksum": _sha1(entry[0]),
                }
            }
        if module_name == "ansible.legacy.file" and module_args["state"] == "directory":
            return self._ensure_directory(module_args["path"], module_args["mode"])
        if module_name == "ansible.legacy.file":
            entry = self.entries[
                module_args["dest"] + module_args["_original_basename"]
            ]
            return {"changed": entry[1] != _mode_bits(module_args["mode"])}
        if module_name == "ansible.legacy.copy":
            return {"changed": True}
        raise AssertionError(f"unexpected module {module_name}")

    def _ensure_directory(self, path, mode):
        entry = self.entries.get(path)
        if entry is None:
            return {"changed": True, "path": path}
        if not isinstance(entry, _Dir):
            return {"failed": True, "msg": f"{path} already exists as a file"}
        return {
            "changed": mode is not None and entry.mode != _mode_bits(mode),
            "path": path,
        }

    def _copy_batch(self, args):
        dest = args["dest"]
        files = [entry["path"] for entry in args["files"]]
        refused = [
            dest + rel
            for rel in [*files, *args["settled"]]
            if isinstance(self.entries.get(dest + rel), (_Dir, _Link))
        ] + [
            dest + rel
            for rel in args["directories"]
            if dest + rel in self.entries
            and not isinstance(self.entries[dest + rel], _Dir)
        ]
        if refused:
            return {"changed": False, "refused": refused}
        archive = self.transfers[-1]
        if list(archive) != files or any(
            _sha1(archive[entry["path"]]) != entry["checksum"]
            for entry in args["files"]
        ):
            return {"failed": True, "msg": "archive does not match files"}
        mode = _mode_bits(args["mode"])
        for rel in files:
            self.entries[dest + rel] = (archive[rel], mode)
        for rel in args["settled"]:
            self.entries[dest + rel] = (self.entries[dest + rel][0], mode)
        for rel in args["directories"]:
            self.entries[dest + rel] = _Dir(_mode_bits(args["directory_mode"] or 0o755))
        return {"changed": True}

    def _state(self, path):
        entry = self.entries.get(path)
        if entry is None or isinstance(entry, _Link):
            return {"isreg": False, "isdir": False, "mode": None, "checksum": None}
        if isinstance(entry, _Dir):
            return {
                "isreg": False,
                "isdir": True,
                "mode": f"{entry.mode:04o}",
                "checksum": None,
            }
        return {
            "isreg": True,
            "isdir": False,
            "mode": f"{entry[1]:04o}",
            "checksum": _sha1(entry[0]),
        }


class _TreeHarness(unittest.TestCase):
    FILES: ClassVar[dict[str, bytes]] = {}
    DEST = "/var/www/public_cdn/roles/app/latest/img/design/"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name)
        for rel, data in self.FILES.items():
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.src / rel).write_bytes(data)

    def tearDown(self):
        self._tmp.cleanup()

    def _synced(self, mode=0o644):
        return {self.DEST + rel: (data, mode) for rel, data in self.FILES.items()}

    def _run(self, remote, *, check_mode=False, diff=False, loader=None, **extra):
        task = _FakeTask(args={"src": f"{self.src}/", "dest": self.DEST, **extra})
        task.check_mode = check_mode
        task.diff = diff
        action = _make_action(task, _FakeTemplar(is_stack_host=True))
        action._connection = _FakeConnection()
        action._loader = _FakeLoader() if loader is None else loader
        action._play_context = _FakePlayContext()
        action._execute_module = remote
        action._transfer_file = getattr(
            remote, "transfer", lambda local, remote_path: remote_path
        )
        action._fixup_perms2 = getattr(remote, "fixup", lambda *a, **k: None)
        action._remove_tmp_path = lambda *a, **k: None
        action._remote_expand_user = lambda path, **k: path

        def make_tmp_path(*a, **k):
            action._connection._shell.tmpdir = "/remote/tmp"
            return "/remote/tmp"

        action._make_tmp_path = make_tmp_path
        return action.run(task_vars={})

    BATCH: ClassVar[list[str]] = [
        "ansible.legacy.file_checksums",
        "ansible.legacy.copy_batch",
    ]

    @staticmethod
    def _batch_args(remote):
        return remote.args[remote.calls.index("ansible.legacy.copy_batch")]

    @staticmethod
    def _copies(remote):
        return [
            args
            for name, args in zip(remote.calls, remote.args, strict=True)
            if name == "ansible.legacy.copy"
        ]


class TestStackHostCopyTree(_TreeHarness):
    FILES: ClassVar[dict[str, bytes]] = {
        "favicon.ico": b"ico",
        "icon.png": b"png",
        "nested/icon.svg": b"<svg/>",
    }

    def _changed(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = (b"old", 0o644)
        return entries

    def test_unchanged_tree_costs_one_remote_call(self):
        remote = _FakeRemote(self._synced())

        result = self._run(remote)

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertEqual(result["dest"], self.DEST)
        self.assertEqual(result["src"], f"{self.src}/")

    def test_changed_file_travels_alone_in_one_batch(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = (b"old", 0o644)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        self.assertEqual(remote.transfers, [{"icon.png": b"png"}])
        self.assertEqual(
            self._batch_args(remote)["files"],
            [{"path": "icon.png", "checksum": _sha1(b"png")}],
        )
        self.assertEqual(sorted(self._batch_args(remote)["tree"]), sorted(self.FILES))
        self.assertEqual(remote.entries, self._synced())

    def test_missing_file_travels_in_one_batch(self):
        entries = self._synced()
        del entries[self.DEST + "nested/icon.svg"]
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        self.assertEqual(remote.transfers, [{"nested/icon.svg": b"<svg/>"}])

    def test_mode_drift_is_settled_without_sending_the_file(self):
        entries = self._synced()
        entries[self.DEST + "favicon.ico"] = (b"ico", 0o600)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        self.assertEqual(remote.transfers, [{}])
        self.assertEqual(self._batch_args(remote)["settled"], ["favicon.ico"])
        self.assertEqual(self._batch_args(remote)["files"], [])

    def test_directory_in_place_of_a_file_is_refused_then_copied_regularly(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = _Dir(0o755)
        remote = _FakeRemote(entries)

        self._run(remote)

        self.assertEqual(remote.calls[:2], self.BATCH)
        self.assertIn("ansible.legacy.stat", remote.calls)
        self.assertIn("ansible.legacy.copy", remote.calls)

    def test_symlink_in_place_of_a_file_is_refused_then_copied_regularly(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = _Link(b"png")
        remote = _FakeRemote(entries)

        self._run(remote)

        self.assertEqual(remote.calls[:2], self.BATCH)
        copies = self._copies(remote)
        self.assertEqual([args["_original_basename"] for args in copies], ["icon.png"])
        self.assertFalse(copies[0]["follow"])

    def test_check_mode_keeps_the_regular_copy(self):
        remote = _FakeRemote(self._changed())

        result = self._run(remote, check_mode=True)

        self.assertTrue(result["changed"])
        self.assertNotIn("ansible.legacy.copy_batch", remote.calls)
        self.assertNotIn("ansible.legacy.copy", remote.calls)
        self.assertIn("ansible.legacy.stat", remote.calls)
        self.assertEqual(remote.transfers, [])

    def test_diff_mode_keeps_the_regular_copy(self):
        remote = _FakeRemote(self._changed())

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True, "diff": [{"after": "png"}]},
        ) as super_run:
            result = self._run(remote, diff=True)

        super_run.assert_called_once()
        self.assertEqual(result["diff"], [{"after": "png"}])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertEqual(remote.transfers, [])

    def test_failed_batch_stays_failed_without_a_second_copy(self):
        failure = {
            "failed": True,
            "changed": True,
            "msg": f"Failed to write {self.DEST}icon.png: boom",
        }

        class _FailingBatch(_FakeRemote):
            def _copy_batch(self, args):
                return dict(failure)

        remote = _FailingBatch(self._changed())

        with patch("plugins.action.stack_host_copy.CopyActionModule.run") as super_run:
            result = self._run(remote)

        super_run.assert_not_called()
        self.assertTrue(result["failed"])
        self.assertIn(f"{self.DEST}icon.png", result["msg"])
        self.assertEqual(remote.calls, self.BATCH)

    def test_batch_result_has_the_keys_of_the_regular_copy(self):
        batch = self._run(_FakeRemote(self._changed()))
        with patch.object(ActionModule, "_write_tree", return_value=None):
            regular = self._run(_FakeRemote(self._changed()))

        self.assertEqual(set(batch), set(regular))
        self.assertEqual(
            {key: batch[key] for key in ("changed", "dest", "src")},
            {key: regular[key] for key in ("changed", "dest", "src")},
        )

    def test_unprivileged_become_keeps_the_regular_copy(self):
        remote = _FakeRemote(self._changed())

        with patch.object(ActionModule, "_is_become_unprivileged", return_value=True):
            result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertNotIn("ansible.legacy.copy_batch", remote.calls)
        self.assertIn("ansible.legacy.copy", remote.calls)

    def test_dest_with_a_variable_skips_the_tree_check(self):
        remote = _FakeRemote(self._changed())
        task = _FakeTask(args={"src": f"{self.src}/", "dest": "/srv/$APP/img/"})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))
        action._execute_module = remote

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": True},
        ) as super_run:
            action.run(task_vars={})

        super_run.assert_called_once()
        self.assertEqual(remote.calls, [])

    def test_archive_over_the_limit_keeps_the_regular_copy(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = (b"old", 0o644)
        entries[self.DEST + "favicon.ico"] = (b"old", 0o644)
        remote = _FakeRemote(entries)

        with patch("plugins.action.stack_host_copy._ARCHIVE_LIMIT", 5):
            result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertNotIn("ansible.legacy.copy_batch", remote.calls)
        self.assertEqual(sorted(remote.transfers), [b"ico", b"png"])

    def test_files_travel_in_the_order_the_copy_action_walks(self):
        remote = _FakeRemote({})

        self._run(remote)

        walked = [
            rel
            for _, rel in _walk_dirs_without_bytecode_caches(
                f"{self.src}/", local_follow=True
            )["files"]
        ]
        sent = [entry["path"] for entry in self._batch_args(remote)["files"]]
        self.assertEqual(sent, walked)
        self.assertEqual(list(remote.transfers[0]), walked)

    def test_checksum_is_taken_from_the_packed_bytes(self):
        remote = _FakeRemote(self._changed())
        icon = self.src / "icon.png"
        loader = _FakeLoader()
        reads = []

        def get_real_file(path, decrypt=True):
            reads.append(path)
            if path == str(icon) and reads.count(path) == 2:
                icon.write_bytes(b"edited")
            return path

        loader.get_real_file = get_real_file

        self._run(remote, loader=loader)

        self.assertEqual(remote.transfers, [{"icon.png": b"edited"}])
        self.assertEqual(
            self._batch_args(remote)["files"],
            [{"path": "icon.png", "checksum": _sha1(b"edited")}],
        )

    def test_requested_mode_is_what_the_tree_check_compares(self):
        remote = _FakeRemote(self._synced(mode=0o600))

        result = self._run(remote, mode="0600")

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])

    def test_attribute_args_skip_the_tree_check(self):
        remote = _FakeRemote(self._synced())

        self._run(remote, owner="root")

        self.assertNotIn("ansible.legacy.file_checksums", remote.calls)
        self.assertIn("ansible.legacy.stat", remote.calls)

    def test_symbolic_mode_skips_the_tree_check(self):
        remote = _FakeRemote(self._synced())

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": False},
        ) as super_run:
            self._run(remote, mode="u=rw,g=r,o=r")

        super_run.assert_called_once()
        self.assertEqual(remote.calls, [])

    def test_failed_tree_check_falls_back_to_the_regular_copy(self):
        remote = _FakeRemote(self._synced())

        def failing(module_name=None, **kwargs):
            if module_name == "ansible.legacy.file_checksums":
                remote.calls.append(module_name)
                return {"failed": True, "msg": "boom"}
            return remote(module_name=module_name, **kwargs)

        result = self._run(failing)

        self.assertFalse(result["changed"])
        self.assertIn("ansible.legacy.stat", remote.calls)

    def test_source_symlink_skips_the_tree_check(self):
        (self.src / "dangling").symlink_to("/nonexistent-target")
        remote = _FakeRemote(self._synced())

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": False},
        ) as super_run:
            self._run(remote, local_follow=False)

        super_run.assert_called_once()
        self.assertEqual(remote.calls, [])

    LEAVES: ClassVar[tuple[str, ...]] = (
        ".claude",
        ".claude/.cc-writes",
        "nested/.claude",
        "nested/.claude/.cc-writes",
    )

    def _add_empty_directories(self):
        for rel in self.LEAVES:
            (self.src / rel).mkdir(parents=True, exist_ok=True)

    def _with_leaves(self, mode):
        entries = self._synced()
        entries.update({self.DEST + rel: _Dir(mode) for rel in self.LEAVES})
        return entries

    def _leaf_paths(self):
        return sorted(self.DEST + rel for rel in self.LEAVES)

    @staticmethod
    def _directory_calls(remote):
        return sorted(
            args["path"]
            for name, args in zip(remote.calls, remote.args, strict=True)
            if name == "ansible.legacy.file" and args["state"] == "directory"
        )

    def test_existing_empty_directories_settle_in_one_remote_call(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o755))

        result = self._run(remote)

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertEqual(
            sorted(remote.args[0]["paths"]),
            sorted([*self._synced(), *self._leaf_paths()]),
        )

    def test_unset_directory_mode_accepts_any_remote_directory_mode(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o700))
        regular = _FakeRemote(self._with_leaves(0o700))

        settled = self._run(remote)
        with patch.object(ActionModule, "_settled_tree", return_value=None):
            copied = self._run(regular)

        self.assertFalse(settled["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertFalse(copied["changed"])
        self.assertEqual(self._directory_calls(regular), self._leaf_paths())

    def test_requested_directory_mode_settles_in_one_remote_call(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o750))

        result = self._run(remote, directory_mode="0750")

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])

    def test_missing_remote_directory_is_ensured_in_one_batch(self):
        self._add_empty_directories()
        entries = self._with_leaves(0o755)
        del entries[self.DEST + "nested/.claude/.cc-writes"]
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        self.assertEqual(
            self._batch_args(remote)["directories"], ["nested/.claude/.cc-writes"]
        )
        self.assertIsNone(self._batch_args(remote)["directory_mode"])

    def test_directory_mode_drift_is_settled_in_one_batch(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o755))

        result = self._run(remote, directory_mode="0750")

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        self.assertEqual(self._batch_args(remote)["directories"], sorted(self.LEAVES))
        self.assertEqual(self._batch_args(remote)["directory_mode"], "0750")

    def test_file_in_place_of_a_directory_is_refused_then_fails_regularly(self):
        self._add_empty_directories()
        entries = self._with_leaves(0o755)
        entries[self.DEST + ".claude/.cc-writes"] = (b"", 0o644)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertEqual(remote.calls[:2], self.BATCH)
        self.assertTrue(result["failed"])
        self.assertIn(self.DEST + ".claude/.cc-writes", self._directory_calls(remote))

    def test_symbolic_directory_mode_with_empty_directories_skips_the_tree_check(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o755))

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            return_value={"changed": False},
        ) as super_run:
            self._run(remote, directory_mode="u=rwx,g=rx,o=")

        super_run.assert_called_once()
        self.assertEqual(remote.calls, [])

    def test_symbolic_directory_mode_without_empty_directories_keeps_the_check(self):
        remote = _FakeRemote(self._synced())

        result = self._run(remote, directory_mode="u=rwx,g=rx,o=")

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])

    def test_integer_mode_is_compared_as_octal(self):
        remote = _FakeRemote(self._synced())

        result = self._run(remote, mode=0o644)

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])

    def _add_bytecode_caches(self):
        for rel in (
            "__pycache__/mod.cpython-314.pyc",
            "nested/__pycache__/mod.cpython-313.pyc",
        ):
            (self.src / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.src / rel).write_bytes(b"bytecode")

    def test_bytecode_caches_stay_out_of_the_tree_check(self):
        self._add_bytecode_caches()
        remote = _FakeRemote(self._synced())

        result = self._run(remote)

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertEqual(sorted(remote.args[0]["paths"]), sorted(self._synced()))

    def test_bytecode_caches_are_not_transferred(self):
        self._add_bytecode_caches()
        entries = self._synced()
        entries[self.DEST + "icon.png"] = (b"old", 0o644)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)
        touched = [str(value) for args in remote.args for value in args.values()]
        self.assertEqual([value for value in touched if "__pycache__" in value], [])
        self.assertEqual(remote.transfers, [{"icon.png": b"png"}])

    def test_bytecode_outside_a_cache_directory_stays_in_the_copy(self):
        (self.src / "legacy.pyc").write_bytes(b"bytecode")
        remote = _FakeRemote(self._synced())

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertIn(self.DEST + "legacy.pyc", remote.args[0]["paths"])
        self.assertEqual(remote.transfers, [{"legacy.pyc": b"bytecode"}])

    def test_symlinked_root_passes_the_cache_filter_unchanged(self):
        with tempfile.TemporaryDirectory() as links:
            root = Path(links) / "root"
            root.symlink_to(self.src)

            filtered = _walk_dirs_without_bytecode_caches(str(root), local_follow=False)

        self.assertEqual(filtered["symlinks"], (str(self.src), "root"))


class TestStackHostCopyFlatTree(_TreeHarness):
    FILES: ClassVar[dict[str, bytes]] = {
        f"slot-{index:02d}.png": f"palette-2-{index}".encode() for index in range(15)
    }

    def _stale(self, names):
        entries = self._synced()
        entries.update({self.DEST + name: (b"palette-1", 0o644) for name in names})
        return entries

    def _round_trips(self, entries, *, regular):
        remote = _FakeRemote(entries)
        if regular:
            with patch.object(ActionModule, "_write_tree", return_value=None):
                result = self._run(remote)
        else:
            result = self._run(remote)
        self.assertTrue(result["changed"])
        return {
            "modules": len(remote.calls),
            "transfers": len(remote.transfers),
            "fixups": remote.fixups,
        }

    def test_all_files_changed_cost_one_transfer_and_two_module_calls(self):
        stale = self._stale(self.FILES)

        before = self._round_trips(stale, regular=True)
        after = self._round_trips(stale, regular=False)

        self.assertEqual(before, {"modules": 31, "transfers": 15, "fixups": 15})
        self.assertEqual(after, {"modules": 2, "transfers": 1, "fixups": 1})

    def test_one_changed_file_costs_one_transfer_and_two_module_calls(self):
        stale = self._stale(["slot-07.png"])

        before = self._round_trips(stale, regular=True)
        after = self._round_trips(stale, regular=False)

        self.assertEqual(before, {"modules": 31, "transfers": 1, "fixups": 1})
        self.assertEqual(after, {"modules": 2, "transfers": 1, "fixups": 1})

    def test_only_the_changed_file_is_sent(self):
        remote = _FakeRemote(self._stale(["slot-07.png"]))

        self._run(remote)

        self.assertEqual(remote.transfers, [{"slot-07.png": b"palette-2-7"}])
        self.assertEqual(remote.entries, self._synced())

    def test_follow_without_symlinks_takes_the_batch(self):
        remote = _FakeRemote(self._stale(["slot-00.png", "slot-01.png"]))

        result = self._run(remote, follow=True)

        self.assertTrue(result["changed"])
        self.assertEqual(remote.calls, self.BATCH)

    def test_follow_onto_a_symlinked_file_keeps_the_copy_semantics(self):
        entries = self._synced()
        entries[self.DEST + "slot-00.png"] = _Link(b"elsewhere")
        remote = _FakeRemote(entries)

        self._run(remote, follow=True)

        self.assertEqual(remote.calls[:2], self.BATCH)
        copies = self._copies(remote)
        self.assertEqual(
            [args["_original_basename"] for args in copies], ["slot-00.png"]
        )
        self.assertTrue(copies[0]["follow"])


class TestStackHostCopyWalkSwap(unittest.TestCase):
    def _action(self):
        task = _FakeTask(args={"src": "x", "dest": "/opt/compose/app/x"})
        return _make_action(task, _FakeTemplar(is_stack_host=True))

    def test_copy_action_walks_without_caches_only_during_the_run(self):
        original = copy_action._walk_dirs
        seen = []

        def copy_run(**kwargs):
            seen.append(copy_action._walk_dirs)
            return {"changed": False}

        with patch(
            "plugins.action.stack_host_copy.CopyActionModule.run",
            side_effect=copy_run,
        ):
            self._action().run(task_vars={})

        self.assertEqual(seen, [_walk_dirs_without_bytecode_caches])
        self.assertIs(copy_action._walk_dirs, original)

    def test_copy_action_walk_is_restored_when_the_copy_raises(self):
        original = copy_action._walk_dirs

        with (
            patch(
                "plugins.action.stack_host_copy.CopyActionModule.run",
                side_effect=RuntimeError("boom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self._action().run(task_vars={})

        self.assertIs(copy_action._walk_dirs, original)


if __name__ == "__main__":
    unittest.main()
