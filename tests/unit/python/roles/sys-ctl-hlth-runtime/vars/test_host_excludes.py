from __future__ import annotations

import os
import posixpath
import unittest
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN
from utils.storage.nfs import get_export_base

from . import PROJECT_ROOT

_ROLES = PROJECT_ROOT / "roles"
_GROUP_PATHS = PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"
_GROUP_PATH_KEYS = ("DIR_VAR_LIB", "DIR_BACKUPS", "DIR_BACKUPS_NODE")
_NFS_CLIENT = "svc-storage-nfs-client"
_NFS_MOUNT_ROLES = (_NFS_CLIENT, "svc-storage-nfs-server")
_NFS_FSTYPE = "{{ STORAGE_NFS_FSTYPE }}"
_INSTALLED_SOFTWARE = (
    "/usr",
    "/etc",
    "/opt",
    "/var/lib/dpkg",
    "/var/lib/pacman",
    "/var/lib/rpm",
    "/usr/lib/sysimage/rpm",
    "/lib/apk/db",
)


def _lookup(name: str) -> str:
    if name == "nfs_export_base":
        return get_export_base()
    raise KeyError(f"no stub for lookup({name!r})")


def _render(template: str, context: Mapping[str, Any]) -> str:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["path_join"] = lambda parts: posixpath.join(*parts)
    env.globals["lookup"] = _lookup
    return env.from_string(template).render(**context)


def _context() -> dict[str, str]:
    paths = load_yaml(str(_GROUP_PATHS))
    context: dict[str, str] = {}
    for key in _GROUP_PATH_KEYS:
        context[key] = _render(paths[key], context)
    for role in _NFS_MOUNT_ROLES:
        role_vars = load_yaml(str(_ROLES / role / ROLE_FILE_VARS_MAIN))
        context.update(
            (key, value)
            for key, value in role_vars.items()
            if isinstance(value, str) and "{{" not in value
        )
    return context


def _tasks(node: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, Mapping):
        yield node
        for key in ("block", "rescue", "always"):
            yield from _tasks(node.get(key))


def _mounts(role: str) -> Iterator[Mapping[str, Any]]:
    tasks_dir = f"{_ROLES / role / 'tasks'}{os.sep}"
    task_files = (
        path
        for path in iter_project_files(extensions=(".yml",))
        if path.startswith(tasks_dir)
    )
    for task_file in sorted(task_files):
        for task in _tasks(load_yaml_any(task_file)):
            mount = task.get("ansible.posix.mount")
            if isinstance(mount, Mapping) and mount.get("state") != "unmounted":
                yield mount


def _nfs_mount_paths(context: Mapping[str, Any]) -> list[str]:
    """
    Returns:
        Every host path, rendered, where the NFS roles mount the shared state.
    """
    return [
        _render(mount["path"], context)
        for role in _NFS_MOUNT_ROLES
        for mount in _mounts(role)
        if mount.get("fstype") == _NFS_FSTYPE
    ]


def _local_bind_paths(context: Mapping[str, Any]) -> list[str]:
    """
    Returns:
        Every host path, rendered, where the NFS client binds a node-local
        tree over the shared state, with that tree.
    """
    return [
        _render(mount[key], context)
        for mount in _mounts(_NFS_CLIENT)
        if "bind" in str(mount.get("opts", "")).split(",")
        for key in ("path", "src")
    ]


def _host_excludes(context: Mapping[str, Any]) -> list[PurePosixPath]:
    declared = load_yaml(str(_ROLES / "sys-ctl-hlth-runtime" / ROLE_FILE_VARS_MAIN))[
        "HEALTH_RUNTIME_HOST_EXCLUDES"
    ]
    return [PurePosixPath(_render(str(entry), context)) for entry in declared]


def _skipped(path: str, excludes: list[PurePosixPath]) -> bool:
    candidate = PurePosixPath(path)
    return any(
        candidate == exclude or exclude in candidate.parents for exclude in excludes
    )


class TestHostScanExcludes(unittest.TestCase):
    def setUp(self) -> None:
        self.context = _context()
        self.excludes = _host_excludes(self.context)

    def test_the_shared_state_and_the_node_backup_store_are_found(self) -> None:
        self.assertIn(self.context["DIR_VAR_LIB"], _nfs_mount_paths(self.context))
        self.assertIn(self.context["DIR_BACKUPS_NODE"], _local_bind_paths(self.context))

    def test_the_host_scan_skips_the_node_local_backup_store(self) -> None:
        for path in _local_bind_paths(self.context):
            with self.subTest(path=path):
                self.assertTrue(
                    _skipped(path, self.excludes),
                    f"the host scan walks {path} on every swarm node: a local "
                    "tree the network mount detection does not see",
                )

    def test_the_host_scan_keeps_installed_software(self) -> None:
        for path in _INSTALLED_SOFTWARE:
            with self.subTest(path=path):
                self.assertFalse(
                    _skipped(path, self.excludes),
                    f"{path} holds installed packages the host scan must read",
                )


if __name__ == "__main__":
    unittest.main()
