"""Detect and rewrite outdated git `ref:` values in `roles/*/meta/services.yml`.

Counterpart to :mod:`utils.update.docker` (which bumps OCI image
`version:` tags). Both share the semver primitives in
:mod:`utils.update.base`; this module owns the recursive walker over
the services map and the upstream-tag lookup via
``git ls-remote --tags <repository>``.

Recursive walker: every dict at any depth (top-level entity,
sub-entity, plugin map, ...) that declares BOTH `repository:` and
`ref:` is a candidate. Only semver-compatible refs are
version-checkable; branches (`master`, `main`, `stable`) and commit
SHAs are skipped.

Each unique repository URL is queried once per run; the result is
reused for every entry pointing at the same repo.

Suppress a check by placing ``# nocheck: repository-version`` on the
line directly above the `ref:` key.
"""

from __future__ import annotations

import concurrent.futures
import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import (
    is_semver,
    latest_semver,
    resolve_max_fetch_workers,
    version_depth,
    version_flavor,
    version_key,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_NOCHECK_MARKER = "repository-version"

_REF_VALUE_RE = re.compile(
    r"^(?P<prefix>\s*ref\s*:\s*)"
    r"(?P<quote>[\"']?)(?P<value>[^\"'#\s]+)(?P=quote)"
    r"(?P<suffix>\s*(?:#.*)?)$"
)


@dataclass(frozen=True)
class RepositoryRefEntry:
    role: str
    entity_path: tuple[str, ...]
    repository: str
    ref: str
    config_path: Path
    line: int


@dataclass(frozen=True)
class RepositoryRefUpdate:
    entry: RepositoryRefEntry
    latest: str


def walk_repo_ref_pairs(
    node, path: tuple[str, ...]
) -> Iterator[tuple[tuple[str, ...], str, str]]:
    """Yield ``(entity_path, repository, ref)`` for every dict in the
    tree that declares both keys with truthy string values."""
    if isinstance(node, dict):
        repo = node.get("repository")
        ref = node.get("ref")
        if isinstance(repo, str) and repo and isinstance(ref, str) and ref:
            yield (path, repo.strip(), ref.strip())
        for key, value in node.items():
            if key in ("repository", "ref"):
                continue
            yield from walk_repo_ref_pairs(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from walk_repo_ref_pairs(item, (*path, f"[{index}]"))


def git_ls_remote_tags(url: str) -> list[str]:
    """Return tag names from ``git ls-remote --tags``, stripped of the
    ``refs/tags/`` prefix and the ``^{}`` peeled-tag marker."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", url],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    tags: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        name = parts[1]
        if not name.startswith("refs/tags/"):
            continue
        name = name[len("refs/tags/") :]
        name = name.removesuffix("^{}")
        if name:
            tags.add(name)
    return sorted(tags)


def _ref_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Return ``(1-indexed line number, ref value)`` for every `ref:`
    declaration in *lines*."""
    out: list[tuple[int, str]] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith(("ref:", "ref :")):
            continue
        try:
            _, value = stripped.split(":", 1)
        except ValueError:
            continue
        value = value.split("#", 1)[0].strip().strip("'\"")
        if value:
            out.append((index, value))
    return out


def suppressed_ref_lines(config_path: Path) -> set[int]:
    """Return 1-indexed line numbers of `ref:` declarations that carry
    a ``# nocheck: repository-version`` marker on the preceding line."""
    raw = read_text(str(config_path))
    lines = raw.splitlines()
    suppressed: set[int] = set()
    for line_no, _ref_value in _ref_lines(lines):
        if is_suppressed_at(lines, line_no, _NOCHECK_MARKER):
            suppressed.add(line_no)
    return suppressed


def collect_entries(repo_root: Path) -> list[RepositoryRefEntry]:
    """Return every semver-checkable ``(repository, ref)`` declaration
    under ``roles/*/meta/services.yml`` whose ref is not suppressed."""
    roles_root = repo_root / "roles"
    entries: list[RepositoryRefEntry] = []
    for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
        services_path = role_dir / ROLE_FILE_META_SERVICES
        if not services_path.is_file():
            continue
        data = load_yaml_any(str(services_path), default_if_missing=None)
        if not isinstance(data, dict):
            continue

        raw = read_text(str(services_path))
        # Sequential ref→line cursor: when the same ref value appears
        # at multiple lines, each candidate consumes the next match so
        # nested entries with identical refs each get their own line.
        ref_line_index: dict[str, list[int]] = {}
        for line_no, ref_value in _ref_lines(raw.splitlines()):
            ref_line_index.setdefault(ref_value, []).append(line_no)

        suppressed = suppressed_ref_lines(services_path)
        for entity_path, repo, ref in walk_repo_ref_pairs(data, ()):
            if not is_semver(ref):
                continue
            candidates = ref_line_index.get(ref) or []
            if not candidates:
                continue
            line_no = candidates.pop(0)
            if line_no in suppressed:
                continue
            entries.append(
                RepositoryRefEntry(
                    role=role_dir.name,
                    entity_path=entity_path,
                    repository=repo,
                    ref=ref,
                    config_path=services_path,
                    line=line_no,
                )
            )
    return entries


def find_outdated_updates(repo_root: Path) -> list[RepositoryRefUpdate]:
    """Cross-reference every collected entry against ``git ls-remote
    --tags`` and return the entries whose ref is older than the latest
    semver tag with the same depth and flavor."""
    entries = collect_entries(repo_root)
    unique_repos = {entry.repository for entry in entries}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=resolve_max_fetch_workers()
    ) as pool:
        repo_tags: dict[str, list[str]] = dict(
            zip(
                unique_repos,
                pool.map(git_ls_remote_tags, unique_repos),
                strict=True,
            )
        )

    updates: list[RepositoryRefUpdate] = []
    for entry in entries:
        tags = repo_tags.get(entry.repository, [])
        if not tags:
            continue
        latest = latest_semver(
            tags,
            version_depth(entry.ref),
            version_flavor(entry.ref),
        )
        if latest and version_key(entry.ref) < version_key(latest):
            updates.append(RepositoryRefUpdate(entry=entry, latest=latest))
    return updates


def update_config_refs(config_path: Path, line_to_new_ref: dict[int, str]) -> bool:
    """Rewrite specific ``ref:`` lines in *config_path*. *line_to_new_ref*
    maps the 1-indexed line number to the desired new value."""
    text = config_path.read_text(  # nocheck: cache-read — read-then-write of the same file; cached read would go stale
        encoding="utf-8"
    )
    lines = text.splitlines(keepends=True)
    changed = False
    for line_no, new_ref in line_to_new_ref.items():
        idx = line_no - 1
        if idx < 0 or idx >= len(lines):
            continue
        match = _REF_VALUE_RE.match(lines[idx].rstrip("\n"))
        if match is None:
            continue
        if match.group("value") == new_ref:
            continue
        quote = match.group("quote")
        rebuilt = (
            f"{match.group('prefix')}{quote}{new_ref}{quote}{match.group('suffix')}"
        )
        if lines[idx].endswith("\n"):
            rebuilt += "\n"
        lines[idx] = rebuilt
        changed = True

    if changed:
        config_path.write_text("".join(lines), encoding="utf-8")
    return changed


def apply_updates(updates: list[RepositoryRefUpdate]) -> list[Path]:
    """Apply every update in *updates* to disk. Returns the list of
    config files that were actually modified."""
    grouped: dict[Path, dict[int, str]] = {}
    for update in updates:
        grouped.setdefault(update.entry.config_path, {})[update.entry.line] = (
            update.latest
        )

    changed_paths: list[Path] = []
    for config_path, line_to_new_ref in sorted(grouped.items()):
        if update_config_refs(config_path, line_to_new_ref):
            changed_paths.append(config_path)
    return changed_paths
