#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path, PurePath
from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.action import copy as _copy_action
from ansible.plugins.action.copy import ActionModule as CopyActionModule
from ansible.plugins.action.copy import _walk_dirs
from ansible.template import trust_as_template
from ansible.utils.hashing import checksum

_IS_STACK_HOST_EXPR = trust_as_template("{{ IS_STACK_HOST | bool }}")
_BYTECODE_CACHE_DIR = "__pycache__"
_TREE_CHECK_ARGS = frozenset(
    {
        "src",
        "dest",
        "mode",
        "directory_mode",
        "force",
        "local_follow",
        "follow",
        "decrypt",
    }
)
_OCTAL_MODE = re.compile(r"^[0-7]{3,4}$")


def _octal(mode: Any) -> int | None:
    if isinstance(mode, int) and not isinstance(mode, bool):
        return mode
    if isinstance(mode, str) and _OCTAL_MODE.match(mode):
        return int(mode, 8)
    return None


def _parents(rel: str) -> list[str]:
    return [str(parent) for parent in PurePath(rel).parents if str(parent) != "."]


def _walk_dirs_without_bytecode_caches(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Walk a source tree like the copy action, minus CPython bytecode caches.

    Args:
        *args: Positional arguments of the copy action's ``_walk_dirs``.
        **kwargs: Keyword arguments of the copy action's ``_walk_dirs``.

    Returns:
        The ``_walk_dirs`` result without the files, directories and symlinks
        at or below a ``__pycache__`` directory.
    """
    tree = _walk_dirs(*args, **kwargs)
    if not isinstance(tree["symlinks"], list):
        return tree
    return {
        kind: [
            entry
            for entry in entries
            if _BYTECODE_CACHE_DIR not in PurePath(entry[1]).parts
        ]
        for kind, entries in tree.items()
    }


class ActionModule(CopyActionModule):
    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if task_vars is None:
            task_vars = {}

        self._templar.available_variables = task_vars
        if not _to_bool(self._templar.template(_IS_STACK_HOST_EXPR)):
            return {
                "changed": False,
                "skipped": True,
                "skip_reason": "IS_STACK_HOST is false; this host does not own the destination",
            }

        self._task.args.setdefault("mode", "0644")
        unchanged = self._unchanged_tree(task_vars)
        if unchanged is not None:
            return unchanged
        walk = _copy_action._walk_dirs
        _copy_action._walk_dirs = _walk_dirs_without_bytecode_caches
        try:
            return super().run(tmp=tmp, task_vars=task_vars)
        finally:
            _copy_action._walk_dirs = walk

    def _unchanged_tree(self, task_vars: dict[str, Any]) -> dict[str, Any] | None:
        """Settle a directory copy whose files all match in one remote call.

        The copy action spends a stat and a file module call per file even
        when nothing differs; any difference, and any argument or source
        shape not modelled here, leaves the decision to the regular copy.

        Args:
            task_vars: Variables of the task, handed to the remote call.

        Returns:
            The unchanged copy result, or ``None`` when the regular copy runs.
        """
        args = self._task.args
        src, dest, mode = args.get("src"), args.get("dest"), _octal(args.get("mode"))
        if (
            self._task.async_val
            or not set(args) <= _TREE_CHECK_ARGS
            or not isinstance(src, str)
            or not src.endswith(os.path.sep)
            or not isinstance(dest, str)
            or not dest.startswith("/")
            or mode is None
            or not _to_bool(args.get("force", True), strict=False)
        ):
            return None
        try:
            source = self._find_needle("files", src)
        except AnsibleError:
            return None
        if not Path(source).is_dir():
            return None
        source = source if source.endswith(os.path.sep) else source + os.path.sep
        shell = self._connection._shell
        tree = _walk_dirs_without_bytecode_caches(
            source,
            local_follow=_to_bool(args.get("local_follow", True), strict=False),
            trailing_slash_detector=shell.path_has_trailing_slash,
        )
        implicit = {parent for _, rel in tree["files"] for parent in _parents(rel)}
        if (
            len(tree["files"]) < 2
            or tree["symlinks"]
            or any(rel not in implicit for _, rel in tree["directories"])
        ):
            return None

        dest = shell.join_path(dest, "")
        decrypt = _to_bool(args.get("decrypt", True), strict=False)
        wanted = {}
        for full, rel in tree["files"]:
            try:
                real = self._loader.get_real_file(full, decrypt=decrypt)
            except AnsibleError:
                return None
            try:
                wanted[shell.join_path(dest, rel)] = checksum(real)
            finally:
                self._loader.cleanup_tmp_file(real)

        found = self._execute_module(
            module_name="ansible.legacy.file_checksums",
            module_args={"paths": sorted(wanted)},
            task_vars=task_vars,
        )
        states = found.get("states")
        if found.get("failed") or not isinstance(states, dict):
            return None
        for path, digest in wanted.items():
            state = states.get(path) or {}
            if (
                not state.get("isreg")
                or state.get("checksum") != digest
                or _octal(state.get("mode")) != mode
            ):
                return None

        self._remove_tmp_path(shell.tmpdir)
        return self._ensure_invocation({"changed": False, "dest": dest, "src": source})
