#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import io
import os
import re
import tarfile
import tempfile
from pathlib import Path, PurePath
from typing import Any

from ansible import constants
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
_ARCHIVE = ".source.tar"
_ARCHIVE_LIMIT = 16 * 1024 * 1024


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
        settled = self._settled_tree(task_vars)
        if settled is not None:
            return settled
        walk = _copy_action._walk_dirs
        _copy_action._walk_dirs = _walk_dirs_without_bytecode_caches
        try:
            return super().run(tmp=tmp, task_vars=task_vars)
        finally:
            _copy_action._walk_dirs = walk

    def _settled_tree(self, task_vars: dict[str, Any]) -> dict[str, Any] | None:
        """Settle a directory copy in one checksum call and one write call.

        The copy action spends a stat and a file module call per file, plus a
        transfer and a copy module call per differing file, and a file module
        call per directory holding no file. Here one remote call compares the
        whole tree; when entries differ outside check and diff mode, the
        differing files travel in one archive and one module call writes them.
        Any argument or source shape not modelled here leaves the decision to
        the regular copy.

        Args:
            task_vars: Variables of the task, handed to the remote calls.

        Returns:
            The copy result, or ``None`` when the regular copy runs.
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
            or "$" in dest
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
        leaves = [rel for _, rel in tree["directories"] if rel not in implicit]
        directory_mode = args.get("directory_mode")
        if (
            len(tree["files"]) < 2
            or tree["symlinks"]
            or (
                leaves and directory_mode is not None and _octal(directory_mode) is None
            )
        ):
            return None

        dest = shell.join_path(dest, "")
        directories = {shell.join_path(dest, rel): rel for rel in leaves}
        decrypt = _to_bool(args.get("decrypt", True), strict=False)
        wanted = {}
        for full, rel in tree["files"]:
            try:
                real = self._loader.get_real_file(full, decrypt=decrypt)
            except AnsibleError:
                return None
            try:
                wanted[shell.join_path(dest, rel)] = (full, rel, checksum(real))
            finally:
                self._loader.cleanup_tmp_file(real)

        found = self._execute_module(
            module_name="ansible.legacy.file_checksums",
            module_args={"paths": sorted([*wanted, *directories])},
            task_vars=task_vars,
        )
        states = found.get("states")
        if found.get("failed") or not isinstance(states, dict):
            return None
        content, settled = {}, []
        for path, (full, rel, digest) in wanted.items():
            state = states.get(path) or {}
            if not state.get("isreg") or state.get("checksum") != digest:
                content[rel] = full
            elif _octal(state.get("mode")) != mode:
                settled.append(rel)
        drifted = []
        for path, rel in directories.items():
            state = states.get(path) or {}
            if not state.get("isdir") or (
                directory_mode is not None
                and _octal(state.get("mode")) != _octal(directory_mode)
            ):
                drifted.append(rel)

        if not (content or settled or drifted):
            self._remove_tmp_path(shell.tmpdir)
            return self._ensure_invocation(
                {"changed": False, "dest": dest, "src": source}
            )
        if self._task.check_mode or self._task.diff or self._is_become_unprivileged():
            return None
        return self._write_tree(
            task_vars,
            source=source,
            dest=dest,
            content=content,
            settled=settled,
            directories=drifted,
            tree=[*(rel for _, rel in tree["files"]), *leaves],
            decrypt=decrypt,
        )

    def _write_tree(
        self,
        task_vars: dict[str, Any],
        *,
        source: str,
        dest: str,
        content: dict[str, str],
        settled: list[str],
        directories: list[str],
        tree: list[str],
        decrypt: bool,
    ) -> dict[str, Any] | None:
        """Write the differing entries of a directory copy in one module call.

        Args:
            task_vars: Variables of the task, handed to the remote call.
            source: The local source directory, with a trailing slash.
            dest: The remote destination directory, with a trailing slash.
            content: Relative path to local path of every file whose remote
                content differs or is missing, in walk order.
            settled: Relative paths of the files whose mode alone differs.
            directories: Relative paths of the leaf directories that are
                missing or whose mode differs.
            tree: Relative paths of every file and leaf directory of the
                source, for the remote check that no two reach one entry.
            decrypt: Whether vaulted source files are decrypted.

        Returns:
            The copy result, or ``None`` when the archive would exceed
            ``_ARCHIVE_LIMIT`` or the module refuses a remote entry, and the
            regular copy runs.
        """
        shell = self._connection._shell
        descriptor, archive = tempfile.mkstemp(
            dir=constants.DEFAULT_LOCAL_TMP, prefix="."
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                files = self._pack(handle, content, decrypt)
            if files is None:
                return None
            if shell.tmpdir is None:
                self._make_tmp_path()
            remote = self._transfer_file(
                archive, shell.join_path(shell.tmpdir, _ARCHIVE)
            )
        finally:
            Path(archive).unlink()
        self._fixup_perms2((shell.tmpdir, remote))
        written = self._execute_module(
            module_name="ansible.legacy.copy_batch",
            module_args={
                "src": remote,
                "dest": dest,
                "files": files,
                "settled": settled,
                "directories": directories,
                "tree": tree,
                "mode": self._task.args["mode"],
                "directory_mode": self._task.args.get("directory_mode"),
            },
            task_vars=task_vars,
        )
        if written.get("refused"):
            return None
        self._remove_tmp_path(shell.tmpdir)
        if written.get("failed"):
            return self._ensure_invocation(written)
        return self._ensure_invocation(
            {"changed": written["changed"], "dest": dest, "src": source}
        )

    def _pack(
        self, handle: Any, content: dict[str, str], decrypt: bool
    ) -> list[dict[str, str]] | None:
        """Write the files of *content* as regular members of a tar archive.

        Args:
            handle: Binary file object the archive is written to.
            content: Relative path to local path of every file, in walk order.
            decrypt: Whether vaulted source files are decrypted.

        Returns:
            ``{path, checksum}`` of every member in walk order, the checksum
            taken from the bytes packed, or ``None`` once the members exceed
            ``_ARCHIVE_LIMIT`` bytes.
        """
        files, size = [], 0
        with tarfile.open(fileobj=handle, mode="w") as bundle:
            for rel, full in content.items():
                real = self._loader.get_real_file(full, decrypt=decrypt)
                try:
                    with Path(real).open("rb") as source:
                        data = source.read(_ARCHIVE_LIMIT + 1 - size)
                finally:
                    self._loader.cleanup_tmp_file(real)
                size += len(data)
                if size > _ARCHIVE_LIMIT:
                    return None
                member = tarfile.TarInfo(rel)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
                files.append(
                    {
                        "path": rel,
                        "checksum": hashlib.sha1(
                            data, usedforsecurity=False
                        ).hexdigest(),
                    }
                )
        return files
