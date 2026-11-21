from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from yaml import YAMLError

from utils.cache.yaml import load_yaml_tagged
from utils.digests import COMMIT
from utils.roles.custom import (
    MANIFEST_COMMIT_KEY,
    MANIFEST_FILE,
    PREFIX,
    RELEASE_TAG,
    is_custom,
)

from .declaration import (
    SOURCE_FIELDS,
    Source,
    embeds_credentials,
    entity_collisions,
    parse_source,
    unrendered,
)

if TYPE_CHECKING:
    from pathlib import Path

MANIFEST_FIELDS: tuple[str, ...] = (*SOURCE_FIELDS, MANIFEST_COMMIT_KEY)


def read_manifest(
    manifest: Path, roles_dir: Path
) -> tuple[dict[str, Source], list[str]]:
    """Args:
        manifest: the ``meta/custom_roles.yml`` of the core checkout; a
            missing file pins nothing.
        roles_dir: the core ``roles/`` the custom roles are placed in.

    Returns:
        ``({group: Source}, errors)``; every source carries the commit its
        tag must resolve to, and each error names its role or the file.
    """
    if not manifest.is_file():
        return {}, []
    try:
        data = load_yaml_tagged(manifest)
    except (OSError, ValueError, YAMLError) as exc:
        return {}, [f"{manifest}: cannot read {MANIFEST_FILE} ({exc})"]
    if not data:
        return {}, []
    if not isinstance(data, dict):
        return {}, [f"{manifest}: {MANIFEST_FILE} must map {PREFIX}<name> to a source"]
    pinned: dict[str, Source] = {}
    errors: list[str] = []
    for group, raw in sorted(data.items(), key=lambda item: str(item[0])):
        source = _entry(str(group), raw, errors)
        if source is not None:
            pinned[str(group)] = source
    errors.extend(entity_collisions(pinned, roles_dir))
    return pinned, errors


def _entry(group: str, raw: object, errors: list[str]) -> Source | None:
    prefix = f"{group}: {MANIFEST_FILE} {group}"
    if not is_custom(group):
        errors.append(f"{prefix} is no custom role; its name must start with {PREFIX}")
        return None
    if not isinstance(raw, dict):
        errors.append(f"{prefix} must be a mapping of {', '.join(MANIFEST_FIELDS)}")
        return None
    before = len(errors)
    fields = {name: value for name, value in raw.items() if name != MANIFEST_COMMIT_KEY}
    source = parse_source(group, fields, prefix, errors)
    errors.extend(_public_url_errors(prefix, fields.get("url")))
    if source is not None and source.version is None:
        errors.append(f"{prefix}.version is missing")
    elif source is not None and not RELEASE_TAG.fullmatch(str(source.version)):
        errors.append(
            f"{prefix}.version '{source.version}' is no release tag vX.Y.Z; a "
            "moving tag, a prerelease or a commit is refused, the commit goes "
            f"into {MANIFEST_COMMIT_KEY}"
        )
    commit = raw.get(MANIFEST_COMMIT_KEY)
    errors.extend(_commit_errors(prefix, commit))
    if source is None or len(errors) > before:
        return None
    return replace(source, pinned_commit=commit)


def _public_url_errors(prefix: str, url: object) -> list[str]:
    if not isinstance(url, str) or unrendered(url) or embeds_credentials(url):
        return []
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return []
    return [
        f"{prefix}.url must be the https URL of a public repository; a private role is declared in the inventory"
    ]


def _commit_errors(prefix: str, commit: object) -> list[str]:
    name = f"{prefix}.{MANIFEST_COMMIT_KEY}"
    if commit is None:
        return [f"{name} is missing"]
    if reason := unrendered(commit):
        return [f"{name} {reason}; the pull never renders it"]
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        return [f"{name} must be the full 40-hex commit SHA the tag resolves to"]
    return []
