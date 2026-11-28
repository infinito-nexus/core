"""Shape validation of the ``storage`` and ``swarm`` blocks an inventory sets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

from .loaders import load_yaml_file

STORAGE_BACKENDS: tuple[str, ...] = ("local", "nfs")

BLOCK_DEFAULTS: dict[str, str] = {
    "storage": "group_vars/all/15_storage.yml",
    "swarm": "group_vars/all/18_swarm.yml",
}

REQUIRED: dict[str, tuple[tuple[str, ...], ...]] = {
    "storage": (("backend",),),
    "swarm": (("network", "encryption"), ("registry", "host"), ("registry", "port")),
}

NFS_REQUIRED: tuple[str, ...] = ("nfs", "server")

_MISSING = object()


def _is_template(value: Any) -> bool:
    return isinstance(value, str) and "{{" in value


def _lookup(block: Any, path: tuple[str, ...]) -> Any:
    node = block
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return _MISSING
        node = node[key]
    return node


def _shape_errors(where: str, value: Any, default: Any) -> list[str]:
    if isinstance(default, dict):
        if not isinstance(value, dict):
            return [f"'{where}' must be a mapping, got {type(value).__name__}"]
        errs: list[str] = []
        for key, sub in value.items():
            if key in default:
                errs.extend(_shape_errors(f"{where}.{key}", sub, default[key]))
            else:
                errs.append(
                    f"'{where}.{key}' is unknown; '{where}' takes "
                    f"{', '.join(sorted(default))}"
                )
        return errs
    expected = type(default)
    if _is_template(value) or (
        isinstance(value, expected)
        and not (expected is int and isinstance(value, bool))
    ):
        return []
    return [f"'{where}' must be {expected.__name__}, got {type(value).__name__}"]


def block_errors(name: str, value: Any, default: dict[str, Any]) -> list[str]:
    """Return why an inventory's ``storage`` or ``swarm`` value cannot replace its default.

    Args:
        name: ``storage`` or ``swarm``.
        value: the value the inventory sets.
        default: the ``group_vars/all`` value of the same name.
    """
    errs = _shape_errors(name, value, default)
    if not isinstance(value, dict):
        return errs
    required = list(REQUIRED[name])
    if name == "storage":
        backend = value.get("backend", _MISSING)
        if (
            backend is not _MISSING
            and not _is_template(backend)
            and backend not in STORAGE_BACKENDS
        ):
            errs.append(
                f"'storage.backend' must be one of {', '.join(STORAGE_BACKENDS)}, "
                f"got {backend!r}"
            )
        if backend == "nfs":
            required.append(NFS_REQUIRED)
    errs.extend(
        f"'{name}.{'.'.join(path)}' is missing; the inventory value replaces "
        f"the group_vars default, so it must set it"
        for path in required
        if _lookup(value, path) is _MISSING
    )
    return errs


def validate_swarm_storage(inv_dir) -> list[str]:
    """Report every malformed ``storage`` or ``swarm`` block of an inventory.

    Args:
        inv_dir: the inventory directory; its ``host_vars/**`` and
            ``group_vars/**`` files are read.

    Returns:
        One message per problem, prefixed with the file that sets the block.
    """
    defaults = {
        name: load_yaml(str(PROJECT_ROOT / path))[name]
        for name, path in BLOCK_DEFAULTS.items()
    }
    root = Path(inv_dir)
    errs: list[str] = []
    files = sorted(
        {*root.glob("host_vars/**/*.yml"), *root.glob("group_vars/**/*.yml")}
    )
    for path in files:
        data = load_yaml_file(path)
        if not isinstance(data, dict):
            continue
        for name, default in defaults.items():
            if name in data:
                errs.extend(
                    f"{path}: {error}"
                    for error in block_errors(name, data[name], default)
                )
    return errs
