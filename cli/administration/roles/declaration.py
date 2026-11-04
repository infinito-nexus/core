"""Custom-role declarations of an inventory, validated before anything is pulled.

``custom`` and ``source`` are read from the raw inventory files and are
never rendered: a templated or tagged value could otherwise make the
controller fetch code chosen at render time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from utils.cache.yaml import TaggedValue
from utils.roles.custom import CUSTOM_KEY, PREFIX, SOURCE_KEY, is_custom
from utils.roles.entity.name import get_entity_name

from .inventory import read_inventory

SOURCE_FIELDS: tuple[str, ...] = ("url", "version", "path")

_JINJA = re.compile(r"{{|{%|{#")
_FULL_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_GIT_URL = re.compile(r"^(?:(?:https|ssh)://\S+|(?:[\w.-]+@)?[\w.-]+:(?!//)\S+)$")
_CONFLICT = object()


@dataclass(frozen=True)
class Source:
    """Where a custom role comes from.

    Args:
        url: Git URL over HTTPS or SSH, or an absolute local directory.
        version: tag or full commit SHA; ``None`` copies the working tree
            of a local directory.
        path: the role directory inside the repository.
    """

    url: str
    version: str | None
    path: str

    @property
    def local(self) -> bool:
        return Path(self.url).is_absolute()

    @property
    def commit(self) -> bool:
        return self.version is not None and bool(_FULL_SHA.match(self.version))

    def describe(self) -> str:
        """Return the source as the pull reports it, without the resolved commit."""
        if self.version is None:
            return f"{self.url} {self.path} (working tree)"
        return f"{self.url} {self.path} @ {self.version}"


def read_declarations(
    inventory: Path, roles_dir: Path
) -> tuple[dict[str, Source], list[str]]:
    """Return the declared custom roles and every declaration error.

    Args:
        inventory: the inventory file, whose directory holds the
            ``group_vars``/``host_vars`` that set application values, or
            an inventory directory.
        roles_dir: the core ``roles/`` the custom roles are placed in.

    Returns:
        ``({group: Source}, errors)``; each error names its group, or the
        inventory file that cannot be read, which declares nothing.
    """
    documents, groups, errors = read_inventory(inventory)
    if errors:
        return {}, errors
    marked: set[str] = set()
    declared: dict[str, Source] = {}
    for group, by_key in sorted(_collect(documents).items()):
        values = {
            key: _agreed(group, key, by_file, errors) for key, by_file in by_key.items()
        }
        if any(value is _CONFLICT for value in values.values()):
            continue
        custom = values.get(CUSTOM_KEY)
        if reason := _unrendered(custom):
            errors.append(
                f"{group}: applications.{group}.{CUSTOM_KEY} {reason}; the pull never renders it"
            )
            continue
        if custom is not True:
            continue
        marked.add(group)
        if not is_custom(group):
            errors.append(
                f"{group}: {CUSTOM_KEY}: true marks a group outside the {PREFIX} prefix"
            )
            continue
        source = _source(group, values.get(SOURCE_KEY), errors)
        if source is not None:
            declared[group] = source
    errors.extend(
        f"{group}: inventory group without applications.{group}.{CUSTOM_KEY}: true"
        for group in sorted(groups)
        if is_custom(group) and group not in marked
    )
    errors.extend(_entity_collisions(declared, roles_dir))
    return declared, errors


def _collect(documents: dict[str, object]) -> dict[str, dict[str, dict[str, object]]]:
    found: dict[str, dict[str, dict[str, object]]] = {}
    for src, data in documents.items():
        apps = data.get("applications") if isinstance(data, dict) else None
        if not isinstance(apps, dict):
            continue
        for group, conf in apps.items():
            if not isinstance(conf, dict):
                continue
            for key in (CUSTOM_KEY, SOURCE_KEY):
                if key in conf:
                    found.setdefault(str(group), {}).setdefault(key, {})[src] = conf[
                        key
                    ]
    return found


def _agreed(
    group: str, key: str, by_file: dict[str, object], errors: list[str]
) -> object:
    values = list(by_file.values())
    if all(value == values[0] for value in values[1:]):
        return values[0]
    errors.append(
        f"{group}: applications.{group}.{key} differs between {', '.join(sorted(by_file))}"
    )
    return _CONFLICT


def _unrendered(value: object) -> str | None:
    if isinstance(value, TaggedValue):
        return f"holds a {value.tag} value"
    if isinstance(value, str):
        return "holds a Jinja expression" if _JINJA.search(value) else None
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return next(filter(None, map(_unrendered, value)), None)
    return None


def _source(group: str, raw: object, errors: list[str]) -> Source | None:
    prefix = f"{group}: applications.{group}.{SOURCE_KEY}"
    if raw is None:
        errors.append(f"{prefix} is missing")
        return None
    if isinstance(raw, TaggedValue):
        errors.append(f"{prefix} holds a {raw.tag} value; the pull never renders it")
        return None
    if not isinstance(raw, dict):
        errors.append(f"{prefix} must be a mapping of {', '.join(SOURCE_FIELDS)}")
        return None
    before = len(errors)
    errors.extend(
        f"{prefix}.{name} is not a source field"
        for name in sorted(set(raw) - set(SOURCE_FIELDS))
    )
    fields: dict[str, str] = {}
    for name in SOURCE_FIELDS:
        value = raw.get(name)
        if value is None:
            continue
        if reason := _unrendered(value):
            errors.append(f"{prefix}.{name} {reason}; the pull never renders it")
        elif not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.{name} must be a non-empty string")
        else:
            fields[name] = value
    url, version, path = (fields.get(name) for name in SOURCE_FIELDS)
    if url is None and "url" not in raw:
        errors.append(f"{prefix}.url is missing")
    if url is not None:
        errors.extend(_url_errors(prefix, url))
    if (
        version is None
        and "version" not in raw
        and not (url is not None and Path(url).is_absolute())
    ):
        errors.append(f"{prefix}.version is missing")
    if path is None and "path" not in raw:
        errors.append(f"{prefix}.path is missing")
    if path is not None:
        errors.extend(_path_errors(group, prefix, PurePosixPath(path)))
    if len(errors) > before or url is None or path is None:
        return None
    return Source(url=url, version=version, path=path)


def _url_errors(prefix: str, url: str) -> list[str]:
    if _embeds_credentials(url):
        return [
            (
                f"{prefix}.url embeds credentials; authenticate through the SSH "
                "agent or SSH configuration of the controller instead"
            )
        ]
    if not (Path(url).is_absolute() or _GIT_URL.match(url)):
        return [
            f"{prefix}.url is neither a Git URL over HTTPS or SSH nor an absolute local directory"
        ]
    return []


def _embeds_credentials(url: str) -> bool:
    if "://" not in url:
        return False
    try:
        parts = urlsplit(url)
        password = parts.password
    except ValueError:
        return True
    return password is not None or (
        parts.scheme != "ssh" and parts.username is not None
    )


def _path_errors(group: str, prefix: str, path: PurePosixPath) -> list[str]:
    # nocheck: project-root-import -- refuses a source.path that climbs out of its repository
    if path.is_absolute() or ".." in path.parts:
        return [f"{prefix}.path must be a relative path inside the repository"]
    if path.name != group:
        return [
            f"{prefix}.path names the role directory '{path.name}', but the group is '{group}'; core never renames a role"
        ]
    return []


def _entity_collisions(declared: dict[str, Source], roles_dir: Path) -> list[str]:
    in_tree = {
        get_entity_name(role.name): role.name
        for role in sorted(roles_dir.iterdir())
        if role.is_dir() and not is_custom(role.name)
    }
    return [
        f"{group}: entity name '{entity}' collides with the in-tree role {in_tree[entity]}"
        for group in sorted(declared)
        if (entity := get_entity_name(group)) in in_tree
    ]
