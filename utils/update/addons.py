"""Shared SPOT for the unified addon contract.

Both the role-meta lint (`tests/lint/ansible/services/test_addons_schema.py`)
and the opt-in external drift checker (`tests/external/update/addons/`) read
the constants here so the two layers never drift apart: the lint validates
that an addon's declared `mechanism`/`source`/`update.catalog` is one the
checker actually understands, and the checker only walks catalogs it has an
adapter for.

This module is intentionally ansible-free and dependency-light so it can be
imported from the lint layer, the external test layer, and the update
automation without dragging deploy-time machinery in.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_DIR_META_ADDONS

MECHANISMS: frozenset[str] = frozenset(
    {"addon", "plugin", "mu_plugin", "extension", "module", "bridge"}
)

SOURCES: frozenset[str] = frozenset({"upstream", "bundled", "vendored", "built"})

ADDON_KEYS: frozenset[str] = frozenset(
    {
        "enabled",
        "required",
        "mechanism",
        "source",
        "bridges",
        "version",
        "group",
        "update",
        "config",
    }
)

UPDATE_KEYS: frozenset[str] = frozenset({"monitored", "catalog", "upstream_id"})

SUPPORTED_CATALOGS: frozenset[str] = frozenset(
    {
        "friendica-addons",
        "nextcloud-appstore",
        "wordpress-org",
        "mediawiki-extension",
        "xwiki-extensions",
        "discourse-meta",
        "odoo-apps",
        "mautrix",
        "gnome-extensions",
        "chrome-webstore",
        "firefox-amo",
        "github-releases",
    }
)

SECRET_KEY_TOKENS: tuple[str, ...] = (
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
)


def secret_key_matches(key: str) -> bool:
    """Return True iff *key* looks like a secret-bearing config key."""
    lowered = key.lower()
    return any(token in lowered for token in SECRET_KEY_TOKENS)


def value_is_templated(value: Any) -> bool:
    """Return True iff *value* is a Jinja expression rather than a bare literal.

    A templated value (`"{{ ... }}"`), whether a `lookup(...,
    'secrets.credentials.<name>')` call or another variable reference, is accepted;
    a bare scalar literal (string without `{{`, or a raw int/bool) is a
    hard-coded secret and is rejected.
    """
    return isinstance(value, str) and "{{" in value


@dataclass(frozen=True)
class AddonEntry:
    """A single addon declaration materialised from a role's meta/addons/<id>.yml."""

    role: str
    addon_id: str
    config_path: Path
    spec: Mapping[str, Any]

    @property
    def mechanism(self) -> str | None:
        value = self.spec.get("mechanism")
        return value if isinstance(value, str) else None

    @property
    def source(self) -> str | None:
        value = self.spec.get("source")
        return value if isinstance(value, str) else None

    @property
    def version(self) -> str:
        value = self.spec.get("version")
        return value if isinstance(value, str) else ""

    @property
    def update(self) -> Mapping[str, Any]:
        value = self.spec.get("update")
        return value if isinstance(value, Mapping) else {}

    @property
    def monitored(self) -> bool:
        return bool(self.update.get("monitored", False))

    @property
    def catalog(self) -> str | None:
        value = self.update.get("catalog")
        return value if isinstance(value, str) else None

    @property
    def upstream_id(self) -> str:
        value = self.update.get("upstream_id")
        return value if isinstance(value, str) and value else self.addon_id


def iter_addon_files(roles_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(role_name, meta/addons/<addon_id>.yml path)`` for every addon
    file across all roles. The filename stem is the addon id."""
    if not roles_root.is_dir():
        return
    for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
        addons_dir = role_dir / ROLE_DIR_META_ADDONS
        if not addons_dir.is_dir():
            continue
        for addon_file in sorted(addons_dir.glob("*.yml")):
            yield role_dir.name, addon_file


def collect_addon_entries(roles_root: Path) -> list[AddonEntry]:
    """Return every declared addon across all roles' ``meta/addons/*.yml``.

    Each file's root IS the addon spec; the filename stem is the addon id.
    Malformed (non-mapping) payloads are skipped here; the lint layer is the
    one that reports them, so the checker stays robust against in-progress
    files.
    """
    entries: list[AddonEntry] = []
    for role_name, addon_file in iter_addon_files(roles_root):
        spec = load_yaml_any(str(addon_file), default_if_missing={})
        if isinstance(spec, Mapping):
            entries.append(
                AddonEntry(
                    role=role_name,
                    addon_id=addon_file.stem,
                    config_path=addon_file,
                    spec=spec,
                )
            )
    return entries


@dataclass
class CatalogSuggestion:
    """A new addon surfaced by a catalog adapter that is not yet declared."""

    role: str
    addon_id: str
    upstream_id: str
    mechanism: str
    source: str
    catalog: str
    catalog_url: str
    reason: str


@dataclass
class VersionSuggestion:
    """An addon whose pinned version is behind the latest upstream release."""

    role: str
    addon_id: str
    current: str
    latest: str
    config_path: Path
    line: int | None = None
    catalog: str = ""


@dataclass
class CatalogResult:
    """What a catalog adapter returned for one discovery/version pass."""

    version_updates: list[VersionSuggestion] = field(default_factory=list)
    new_addons: list[CatalogSuggestion] = field(default_factory=list)


def worker_fetch_limit(default: int = 8) -> int:
    """Thread-pool size for live catalog fetches, from INFINITO_WORKER_FETCH."""
    raw = os.environ.get("INFINITO_WORKER_FETCH")
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class CatalogCandidate:
    """A single entry a catalog adapter surfaced for relevance + version review."""

    upstream_id: str
    latest: str
    mechanism: str
    source: str
    catalog_url: str
    relevant: bool = True
    reason: str = ""


def version_is_newer(current: str, latest: str) -> bool:
    """Return True iff *latest* is a strictly newer semver than *current*.

    A blank ``current`` (the addon tracks the app default) never produces a
    suggestion, and a non-semver ``latest`` is ignored so the checker never
    proposes a non-comparable tag.
    """
    from utils.update.base import is_semver, version_key

    if not current or not is_semver(current) or not is_semver(latest):
        return False
    return version_key(latest) > version_key(current)


def discover_addon_updates(
    *,
    role: str,
    catalog: str,
    declared: list[AddonEntry],
    candidates: list[CatalogCandidate],
) -> CatalogResult:
    """Reconcile a catalog's live candidates against the declared addons.

    Pure, fixture-friendly core of the external drift checker (no I/O): the
    live adapter fans the registry queries out and hands the results here.

    * A monitored declared addon whose pinned ``version`` is behind the
      candidate's ``latest`` becomes a :class:`VersionSuggestion`.
    * A *relevant* candidate with no matching declared addon becomes a
      :class:`CatalogSuggestion` (added disabled by update automation).
    * A candidate the curated relevance rules reject is silently dropped so
      broad marketplaces never produce unreviewable noise.
    """
    result = CatalogResult()
    by_upstream = {entry.upstream_id: entry for entry in declared}

    for candidate in candidates:
        if not candidate.relevant:
            continue
        entry = by_upstream.get(candidate.upstream_id)
        if entry is None:
            result.new_addons.append(
                CatalogSuggestion(
                    role=role,
                    addon_id=candidate.upstream_id,
                    upstream_id=candidate.upstream_id,
                    mechanism=candidate.mechanism,
                    source=candidate.source,
                    catalog=catalog,
                    catalog_url=candidate.catalog_url,
                    reason=candidate.reason
                    or f"catalog {catalog} lists {candidate.upstream_id}",
                )
            )
        elif entry.monitored and version_is_newer(entry.version, candidate.latest):
            result.version_updates.append(
                VersionSuggestion(
                    role=role,
                    addon_id=entry.addon_id,
                    current=entry.version,
                    latest=candidate.latest,
                    config_path=entry.config_path,
                    catalog=catalog,
                )
            )
    return result
