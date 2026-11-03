import hashlib
import os
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


def _mode_bits(mode):
    return mode if isinstance(mode, int) else int(mode, 8)


class _FakeRemote:
    def __init__(self, entries):
        self.entries = dict(entries)
        self.calls = []
        self.args = []

    def __call__(self, module_name=None, module_args=None, task_vars=None, **kwargs):
        self.calls.append(module_name)
        self.args.append(module_args)
        if module_name == "ansible.legacy.file_checksums":
            return {
                "changed": False,
                "states": {p: self._state(p) for p in module_args["paths"]},
            }
        if module_name == "ansible.legacy.stat":
            entry = self.entries.get(module_args["path"])
            if entry is None:
                return {"stat": {"exists": False}}
            if isinstance(entry, _Dir):
                return {"stat": {"exists": True, "isdir": True}}
            return {
                "stat": {"exists": True, "isdir": False, "checksum": _sha1(entry[0])}
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

    def _state(self, path):
        entry = self.entries.get(path)
        if entry is None:
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


class TestStackHostCopyTree(unittest.TestCase):
    FILES: ClassVar[dict[str, bytes]] = {
        "favicon.ico": b"ico",
        "icon.png": b"png",
        "nested/icon.svg": b"<svg/>",
    }
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

    def _run(self, remote, **extra):
        task = _FakeTask(args={"src": f"{self.src}/", "dest": self.DEST, **extra})
        action = _make_action(task, _FakeTemplar(is_stack_host=True))
        action._connection = _FakeConnection()
        action._loader = _FakeLoader()
        action._play_context = _FakePlayContext()
        action._execute_module = remote
        action._transfer_file = lambda local, remote_path: remote_path
        action._fixup_perms2 = lambda *a, **k: None
        action._remove_tmp_path = lambda *a, **k: None
        action._remote_expand_user = lambda path, **k: path

        def make_tmp_path(*a, **k):
            action._connection._shell.tmpdir = "/remote/tmp"
            return "/remote/tmp"

        action._make_tmp_path = make_tmp_path
        return action.run(task_vars={})

    def test_unchanged_tree_costs_one_remote_call(self):
        remote = _FakeRemote(self._synced())

        result = self._run(remote)

        self.assertFalse(result["changed"])
        self.assertEqual(remote.calls, ["ansible.legacy.file_checksums"])
        self.assertEqual(result["dest"], self.DEST)
        self.assertEqual(result["src"], f"{self.src}/")

    def test_changed_file_runs_the_regular_copy(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = (b"old", 0o644)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertIn("ansible.legacy.copy", remote.calls)

    def test_missing_file_runs_the_regular_copy(self):
        entries = self._synced()
        del entries[self.DEST + "nested/icon.svg"]
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertIn("ansible.legacy.copy", remote.calls)

    def test_mode_drift_runs_the_regular_copy(self):
        entries = self._synced()
        entries[self.DEST + "favicon.ico"] = (b"ico", 0o600)
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertIn("ansible.legacy.file", remote.calls)

    def test_directory_in_place_of_a_file_runs_the_regular_copy(self):
        entries = self._synced()
        entries[self.DEST + "icon.png"] = _Dir(0o755)
        remote = _FakeRemote(entries)

        self._run(remote)

        self.assertIn("ansible.legacy.stat", remote.calls)

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
        with patch.object(ActionModule, "_unchanged_tree", return_value=None):
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

    def test_missing_remote_directory_runs_the_regular_copy(self):
        self._add_empty_directories()
        entries = self._with_leaves(0o755)
        del entries[self.DEST + "nested/.claude/.cc-writes"]
        remote = _FakeRemote(entries)

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertEqual(self._directory_calls(remote), self._leaf_paths())

    def test_directory_mode_drift_runs_the_regular_copy(self):
        self._add_empty_directories()
        remote = _FakeRemote(self._with_leaves(0o755))

        result = self._run(remote, directory_mode="0750")

        self.assertTrue(result["changed"])
        self.assertEqual(self._directory_calls(remote), self._leaf_paths())

    def test_file_in_place_of_a_directory_runs_the_regular_copy(self):
        self._add_empty_directories()
        entries = self._with_leaves(0o755)
        entries[self.DEST + ".claude/.cc-writes"] = (b"", 0o644)
        remote = _FakeRemote(entries)

        result = self._run(remote)

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
        self.assertIn("ansible.legacy.copy", remote.calls)
        touched = [str(value) for args in remote.args for value in args.values()]
        self.assertEqual([value for value in touched if "__pycache__" in value], [])

    def test_bytecode_outside_a_cache_directory_stays_in_the_copy(self):
        (self.src / "legacy.pyc").write_bytes(b"bytecode")
        remote = _FakeRemote(self._synced())

        result = self._run(remote)

        self.assertTrue(result["changed"])
        self.assertIn(self.DEST + "legacy.pyc", remote.args[0]["paths"])
        self.assertIn("ansible.legacy.copy", remote.calls)

    def test_symlinked_root_passes_the_cache_filter_unchanged(self):
        with tempfile.TemporaryDirectory() as links:
            root = Path(links) / "root"
            root.symlink_to(self.src)

            filtered = _walk_dirs_without_bytecode_caches(str(root), local_follow=False)

        self.assertEqual(filtered["symlinks"], (str(self.src), "root"))


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
