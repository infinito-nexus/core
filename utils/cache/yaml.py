"""In-process YAML loader with per-path memoisation.

Many CLI tools walk the same `roles/<role>/<config|vars|meta>/...yml`
files multiple times during a single invocation (dependency resolution,
service resolution, role introspection, ...). Each direct
`yaml.safe_load(path.read_text())` re-parses YAML and re-touches disk.

This module exposes a single cached `load_yaml(path)` so each absolute
path is parsed at most once per Python process. `dump_yaml` writes
through and evicts the cached entry. `invalidate(path)` is the explicit
escape hatch when a caller knows a file was changed externally.

CACHE SEMANTICS
- Cache key: `(str(Path(path).resolve()), st_mtime_ns, st_size)`.
  Symlinks resolve once at the cache boundary so the same target shares
  an entry regardless of how callers spell the path. The mtime+size
  signature invalidates entries whenever the file is rewritten by an
  external process (e.g. Ansible's `copy:` module persisting tokens
  while the same Python process keeps running across many calls).
- Cached value: the **list of documents** ``yaml.safe_load_all`` returns
  for that file. Single-document YAML files cache as a 1-element list,
  so a callsite that asks for the single doc (``load_yaml`` /
  ``load_yaml_any``) and a callsite that asks for the multi-doc list
  (``load_yaml_all``) share **the same parse**. The same list / dict
  instances are returned to every caller, so callers that mutate the
  result MUST `copy.deepcopy()` it first. Treat the value as read-only.
- Lifetime: process-wide. CLI tools that never rewrite their inputs see
  the same hit rate as before; long-lived Ansible processes pick up
  out-of-band writes on the very next read.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


def _construct_compose_merge_tag(loader, node):
    """Docker-compose merge tags (!override/!reset) parse as their value."""
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


for _tag in ("!override", "!reset"):
    yaml.SafeLoader.add_constructor(_tag, _construct_compose_merge_tag)


def _construct_vault_tag(loader, node):
    return loader.construct_scalar(node)


yaml.SafeLoader.add_constructor("!vault", _construct_vault_tag)

_MISSING = object()
_CACHE: dict[tuple[str, int, int], list[Any]] = {}


def _path_key(path) -> str:
    return str(Path(path).resolve())


def _key(path) -> str:
    return _path_key(path)


def _signature(p: Path) -> tuple[str, int, int]:
    st = p.stat()
    return (_path_key(p), st.st_mtime_ns, st.st_size)


def _load_docs(path) -> list[Any]:
    """Return the cached list of YAML documents for *path*, parsing on
    cache miss. The caller must already have verified that the file
    exists; missing-file handling is the public helper's job (so the
    synthetic ``default_if_missing`` value never enters the cache and a
    later ``dump_yaml`` is picked up cleanly).
    """
    p = Path(path)
    sig = _signature(p)
    if sig in _CACHE:
        return _CACHE[sig]

    path_str = sig[0]
    for stale_key in [k for k in _CACHE if k[0] == path_str and k != sig]:
        _CACHE.pop(stale_key, None)

    with p.open("r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))  # nocheck: direct-yaml
    _CACHE[sig] = docs
    return docs


def _load_raw(path, *, default_if_missing: Any) -> Any:
    """Cached single-doc parse without root-shape validation.

    Returns whatever the YAML root produces (dict, list, scalar, or
    ``{}`` for empty files). Multi-document files raise ``ValueError``
    so callers that expect a single doc fail loud, matching the legacy
    ``yaml.safe_load(...)`` behaviour.
    """
    p = Path(path)
    if not p.exists():
        if default_if_missing is _MISSING:
            raise FileNotFoundError(p)
        return default_if_missing

    docs = _load_docs(p)
    if not docs:
        return {}
    if len(docs) > 1:
        raise ValueError(
            f"Expected a single YAML document in {path}, got {len(docs)}; "
            "use load_yaml_all() for multi-document files."
        )
    data = docs[0]
    return {} if data is None else data


def load_yaml(path, *, default_if_missing: Any = _MISSING) -> dict[str, Any]:
    """Load a YAML file as a dict, memoised by absolute path.

    `default_if_missing` controls the missing-file behaviour:
    - Default (`_MISSING`): raise `FileNotFoundError` for callers that
      want to fail loud (resolution code).
    - Pass a value (typically `{}`): return that value when the file
      does not exist, matching the behaviour expected by
      `cli.administration.inventory.provision.yaml_io.load_yaml`.

    Raises `TypeError` when the YAML root is not a mapping; use
    `load_yaml_any` for files whose root is a list or scalar.
    """
    data = _load_raw(path, default_if_missing=default_if_missing)
    if not isinstance(data, dict):
        raise TypeError(
            f"Expected a YAML mapping at top-level in {path}, got {type(data).__name__}"
        )
    return data


def load_yaml_any(path, *, default_if_missing: Any = _MISSING) -> Any:
    """Memoised YAML load that accepts any root shape (dict, list,
    scalar). Use this for files where the root is not a mapping (e.g.
    Ansible task lists, the root list in `meta/variants.yml`).

    Empty files surface as `{}` (matching `yaml.safe_load(...) or {}`
    semantics that most call sites already rely on).
    """
    return _load_raw(path, default_if_missing=default_if_missing)


def dump_yaml(path, data: Any) -> None:
    """Write `data` to `path` as YAML and evict the cached entry.

    Accepts any safe-dumpable Python structure (dict, list of dicts,
    scalar). The next `load_yaml*` call for `path` will parse the
    just-written file and refill the cache, which is what callers
    expect when a CLI tool or test fixture edits a file mid-run.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data) if isinstance(data, Mapping) else data
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(  # nocheck: direct-yaml — this module IS the cache.
            payload, f, sort_keys=False, default_flow_style=False
        )
    _drop_path(p)


def dump_yaml_str(
    data: Any,
    *,
    sort_keys: bool = False,
    default_flow_style: bool = False,
) -> str:
    """Serialise *data* to a YAML string.

    Use this for stdout output, log messages, or any place a YAML
    representation is needed without an on-disk file. There is no
    cache involved (the destination is a string, not a path), but the
    helper exists so callers don't have to ``import yaml`` just to call
    ``yaml.safe_dump`` — keeping every YAML touchpoint in
    ``utils.cache.yaml``.
    """
    return yaml.safe_dump(  # nocheck: direct-yaml — this module IS the cache.
        data, sort_keys=sort_keys, default_flow_style=default_flow_style
    )


def load_yaml_str(text: str) -> Any:
    """Parse a YAML string.

    Use this when the YAML payload comes from somewhere other than a
    file (HTTP response body, stdin, an intermediate buffer). The
    path-keyed cache cannot help here — every call parses afresh — but
    the helper exists for symmetry with :func:`dump_yaml_str` so
    callers never have to ``import yaml`` directly.
    """
    return yaml.safe_load(text)  # nocheck: direct-yaml — this module IS the cache.


def load_yaml_all(path, *, default_if_missing: Any = _MISSING) -> list:
    """Memoised multi-document YAML load.

    Returns the list of documents from a multi-doc YAML file
    (``--- ... --- ...``). Shares the unified per-path cache with
    :func:`load_yaml_any` / :func:`load_yaml`, so loading a file as
    multi-doc and then as single-doc (or vice versa) parses it exactly
    once.
    """
    p = Path(path)
    if not p.exists():
        if default_if_missing is _MISSING:
            raise FileNotFoundError(p)
        return default_if_missing
    return _load_docs(p)


def load_yaml_all_str(text: str) -> list:
    """Parse a multi-document YAML string into a list of documents.

    No caching (the source is a string, not a path) — provided for
    symmetry with :func:`load_yaml_str` so callers never need
    ``import yaml`` for the parse.
    """
    # This module IS the cache; calling itself would recurse.
    return list(yaml.safe_load_all(text))  # nocheck: direct-yaml


def _drop_path(path) -> None:
    """Drop every cache entry for `path`."""
    path_str = _path_key(path)
    for stale_key in [k for k in _CACHE if k[0] == path_str]:
        _CACHE.pop(stale_key, None)


def invalidate(path) -> None:
    """Drop one path from the cache.

    Use when the file was changed by code that does not go through
    `dump_yaml` (e.g. an external subprocess, a manual file rewrite,
    a fixture in tests). With the mtime+size cache key, normal
    out-of-band writes invalidate automatically; this helper is the
    explicit escape hatch when the timestamps must not be trusted.
    """
    _drop_path(path)


def _reset() -> None:
    """Test-only helper: clear the entire cache.

    Named ``_reset`` for parity with the per-domain reset helpers in
    sibling modules (``applications._reset``, ``users._reset``,
    ``domains._reset``, ``base._reset``); ``utils.cache._reset_cache_for_tests``
    orchestrates calls to all of them.
    """
    _CACHE.clear()


_reset_cache_for_tests = _reset
