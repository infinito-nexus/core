"""Bounded upstream catalog discovery for the unified addon contract.

Each adapter reads one upstream listing; :func:`discover_catalog_entries`
reconciles it against the declared addons through
:func:`utils.update.addons.discover_addon_updates`, and
:func:`write_suggestion` declares a discovered entry hard-off, the way
update automation adds it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.yaml import dump_yaml_str
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_DIR_META_ADDONS
from utils.update.addons import (
    CatalogCandidate,
    CatalogResult,
    CatalogSuggestion,
    collect_addon_entries,
    discover_addon_updates,
)
from utils.update.base import is_semver, version_flavor, version_key

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

INTEGRATION_AXIS_PREFIXES: tuple[str, ...] = ("web-app-", "web-svc-")

PROTOCOL_TERMS: frozenset[str] = frozenset({"ldap", "oidc", "openid", "saml"})

_TOKEN = re.compile(r"[a-z0-9]+")

_ADDON_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

Listing = list[tuple[str, str]]


def parse_github_directories(body: str) -> Listing:
    """Return ``(name, "")`` for every top-level directory of a GitHub contents listing.

    Args:
        body: JSON answer of ``GET /repos/<owner>/<repo>/contents``.
    """
    return [
        (item["name"], "")
        for item in json.loads(body)
        if item.get("type") == "dir" and not item["name"].startswith(".")
    ]


def parse_nextcloud_apps(body: str) -> Listing:
    """Return ``(app id, newest stable release)`` for every app of the Nextcloud app store.

    Args:
        body: JSON answer of ``GET /api/v1/apps.json``.
    """
    listing: Listing = []
    for app in json.loads(body):
        stable = [
            str(release.get("version", ""))
            for release in app.get("releases") or []
            if is_semver(str(release.get("version", "")))
            and not version_flavor(str(release.get("version", "")))
        ]
        listing.append((app["id"], max(stable, key=version_key, default="")))
    return listing


@dataclass(frozen=True)
class CatalogAdapter:
    """One bounded upstream listing that catalog discovery reads.

    Args:
        url: the listing, fetched once per run.
        page: review URL of one entry, formatted with ``upstream_id``.
        parse: turns the listing body into ``(upstream_id, latest)`` pairs.
        mechanism: the ``mechanism`` a discovered entry is declared with.
    """

    url: str
    page: str
    parse: Callable[[str], Listing]
    mechanism: str


CATALOG_ADAPTERS: Mapping[str, CatalogAdapter] = {
    "friendica-addons": CatalogAdapter(
        url="https://api.github.com/repos/friendica/friendica-addons/contents",
        page="https://github.com/friendica/friendica-addons/tree/develop/{upstream_id}",
        parse=parse_github_directories,
        mechanism="addon",
    ),
    "nextcloud-appstore": CatalogAdapter(
        url="https://apps.nextcloud.com/api/v1/apps.json",
        page="https://apps.nextcloud.com/apps/{upstream_id}",
        parse=parse_nextcloud_apps,
        mechanism="plugin",
    ),
}


def partner_terms(roles_root: Path) -> frozenset[str]:
    """Return the entity name of every in-repo integration partner plus the SSO/LDAP protocols.

    Args:
        roles_root: the repository's ``roles`` directory.
    """
    return PROTOCOL_TERMS | {
        entity_name(path.name)
        for path in roles_root.iterdir()
        if path.is_dir() and path.name.startswith(INTEGRATION_AXIS_PREFIXES)
    }


def relevant_term(upstream_id: str, terms: frozenset[str], own: str) -> str | None:
    """Return the partner term an upstream id names, None when it names none.

    A token matches a term it equals; a term of four or more characters also
    matches a token it starts, so ``ldapauth`` names ``ldap`` while ``editor``
    does not name ``tor``.

    Args:
        upstream_id: the catalog entry's id.
        terms: the curated relevance terms, see :func:`partner_terms`.
        own: the hosting role's entity name, never a partner of itself.
    """
    tokens = _TOKEN.findall(upstream_id.lower())
    return next(
        (
            term
            for term in sorted(terms - {own})
            if any(
                token == term or (len(term) >= 4 and token.startswith(term))
                for token in tokens
            )
        ),
        None,
    )


def discover_catalog_entries(
    roles_root: Path,
    fetch: Callable[[str], str],
    adapters: Mapping[str, CatalogAdapter] = CATALOG_ADAPTERS,
) -> CatalogResult:
    """Run each catalog adapter against the roles that monitor that catalog.

    A role meets a catalog only through an addon whose ``update.catalog``
    names it, and a listed entry only counts when :func:`relevant_term` finds
    an integration partner in its id, so a broad marketplace never reaches
    the result unfiltered. A listing that cannot be read is reported under
    ``unreachable`` instead of raising.

    Args:
        roles_root: the repository's ``roles`` directory.
        fetch: returns the body of a listing URL.
        adapters: catalog name to adapter.
    """
    entries = collect_addon_entries(roles_root)
    terms = partner_terms(roles_root)
    result = CatalogResult()
    pairs = sorted(
        {(e.role, e.catalog) for e in entries if e.monitored and e.catalog in adapters}
    )
    for role, catalog in pairs:
        adapter = adapters[catalog]
        try:
            listing = adapter.parse(fetch(adapter.url))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.unreachable.append(f"{role}: {catalog} ({adapter.url}): {exc}")
            continue
        own = entity_name(role)
        candidates = []
        for upstream_id, latest in listing:
            term = relevant_term(upstream_id, terms, own)
            candidates.append(
                CatalogCandidate(
                    upstream_id=upstream_id,
                    latest=latest,
                    mechanism=adapter.mechanism,
                    source="upstream",
                    catalog_url=adapter.page.format(upstream_id=upstream_id),
                    relevant=term is not None,
                    reason=f"its id names the integration partner '{term}'",
                )
            )
        found = discover_addon_updates(
            role=role,
            catalog=catalog,
            declared=[e for e in entries if e.role == role],
            candidates=candidates,
        )
        result.version_updates.extend(found.version_updates)
        result.new_addons.extend(found.new_addons)
    return result


def write_suggestion(roles_root: Path, suggestion: CatalogSuggestion) -> Path:
    """Declare a discovered addon as ``meta/addons/<id>.yml``, disabled and optional.

    The file carries the complete ``update`` block and no ``config``, so no
    credential can enter through discovery, and an existing declaration is
    never overwritten.

    Args:
        roles_root: the repository's ``roles`` directory.
        suggestion: the catalog entry to declare.

    Returns:
        The path of the written file.
    """
    if not _ADDON_ID.fullmatch(suggestion.addon_id):
        raise ValueError(f"{suggestion.addon_id!r} is not a safe addon file name")
    role_dir = roles_root / suggestion.role
    if not role_dir.is_dir():
        raise ValueError(f"{suggestion.role!r} is not a role under {roles_root}")
    path = role_dir / ROLE_DIR_META_ADDONS / f"{suggestion.addon_id}.yml"
    if path.exists():
        raise FileExistsError(path)
    spec = {
        "enabled": False,
        "required": False,
        "mechanism": suggestion.mechanism,
        "source": suggestion.source,
        "update": {
            "monitored": True,
            "catalog": suggestion.catalog,
            "upstream_id": suggestion.upstream_id,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + dump_yaml_str(spec), encoding="utf-8")
    return path
