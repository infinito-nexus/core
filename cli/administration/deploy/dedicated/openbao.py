from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from pathlib import Path
from typing import Any

from utils.cache.yaml import load_yaml_tagged
from utils.openbao_client import (
    CREDENTIALS_PATH,
    LOGIN_ENV,
    USERS_KEY,
    OpenBaoError,
    Reference,
    login,
    references,
    user_references,
)

INVENTORY_SUFFIXES = (".yml", ".yaml")
VARS_DIRS = ("group_vars", "host_vars")


class OpenBaoPreflightError(Exception):
    pass


def inventory_files(inventory: str) -> list[Path]:
    """
    Args:
        inventory: the inventory file or directory the deploy is handed.

    Returns:
        The inventory file and every YAML file of its ``group_vars`` and
        ``host_vars``.
    """
    path = Path(inventory)
    root = path if path.is_dir() else path.parent
    files = [path] if path.is_file() and path.suffix in INVENTORY_SUFFIXES else []
    for name in VARS_DIRS:
        directory = root / name
        if directory.is_dir():
            files.extend(
                sorted(
                    candidate
                    for candidate in directory.rglob("*")
                    if candidate.is_file() and candidate.suffix in INVENTORY_SUFFIXES
                )
            )
    return files


def _applications(node: Any) -> Iterator[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        return
    applications = node.get("applications")
    if isinstance(applications, Mapping):
        yield applications
    for value in node.values():
        if isinstance(value, Mapping) and value is not applications:
            yield from _applications(value)


def _users(node: Any) -> Iterator[Mapping[str, Any]]:
    if not isinstance(node, Mapping):
        return
    users = node.get(USERS_KEY)
    if isinstance(users, Mapping):
        yield users
    for key, value in node.items():
        if key not in (USERS_KEY, "applications") and isinstance(value, Mapping):
            yield from _users(value)


def _credentials(config: Any) -> Any:
    for key in CREDENTIALS_PATH:
        config = config.get(key) if isinstance(config, Mapping) else None
    return config


def inventory_references(inventory: str) -> list[tuple[str, Reference]]:
    """
    Args:
        inventory: see ``inventory_files``.

    Returns:
        Every OpenBao reference under ``applications.<id>.secrets.credentials``
        and in ``users.<name>.password``, with the credential's dotted name, in
        file order.
    """
    found: list[tuple[str, Reference]] = []
    for path in inventory_files(inventory):
        document = load_yaml_tagged(path)
        entries: list[tuple[str, Reference]] = []
        try:
            for applications in _applications(document):
                for application_id, config in applications.items():
                    prefix = f"{application_id}.{'.'.join(CREDENTIALS_PATH)}"
                    entries.extend(references(_credentials(config), prefix))
            for users in _users(document):
                entries.extend(
                    (".".join(parts), reference)
                    for parts, reference in user_references(users)
                )
        except OpenBaoError as exc:
            raise OpenBaoPreflightError(f"{path}: {exc}") from None
        found.extend(entry for entry in entries if entry not in found)
    return found


def prepare(inventory: str, environ: MutableMapping[str, str]) -> int:
    """
    Args:
        inventory: see ``inventory_files``.
        environ: the controller's environment; it receives ``BAO_TOKEN`` for
            the play and is the only place the token goes.

    Returns:
        How many references the pre-flight read, 0 when the inventory holds
        none and no login took place.
    """
    found = inventory_references(inventory)
    if not found:
        return 0
    try:
        client = login(environ)
    except OpenBaoError as exc:
        raise OpenBaoPreflightError(
            f"the inventory holds {len(found)} OpenBao references: {exc}"
        ) from None
    failures: list[str] = []
    for name, reference in found:
        try:
            client.read(reference)
        except OpenBaoError as exc:
            failures.append(f"credential {name}: {exc}")
    if failures:
        raise OpenBaoPreflightError(
            "the OpenBao pre-flight failed before any host was contacted:\n  "
            + "\n  ".join(failures)
        )
    environ[LOGIN_ENV] = client.token or ""
    return len(found)
