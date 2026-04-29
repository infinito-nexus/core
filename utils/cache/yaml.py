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
- Cached value: the dict returned by `yaml.safe_load`. **The same dict
  instance is returned to every caller**, so callers that mutate the
  result MUST `copy.deepcopy()` it first. Treat the value as read-only.
- Lifetime: process-wide. CLI tools that never rewrite their inputs see
  the same hit rate as before; long-lived Ansible processes pick up
  out-of-band writes on the very next read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import yaml


_MISSING = object()
_CACHE: Dict[Tuple[str, int, int], Any] = {}


def _path_key(path) -> str:
    return str(Path(path).resolve())


def _key(path) -> str:
    # Backwards-compatible: `invalidate(path)` and `dump_yaml`'s eviction
    # work with just the path. The full cache key lookup takes mtime/size
    # into account separately in `_load_raw`.
    return _path_key(path)


def _signature(p: Path) -> Tuple[str, int, int]:
    st = p.stat()
    return (_path_key(p), st.st_mtime_ns, st.st_size)


def _load_raw(path, *, default_if_missing: Any) -> Any:
    """Cached parse without root-shape validation.

    Returns whatever `yaml.safe_load` produces (dict, list, scalar,
    None coerced to `{}` for empty files). Callers wrap this with
    their own validation.

    Cache invalidates when the file's mtime or size changes, so a write
    by Ansible's `copy:` module is picked up on the next read in the
    same Python process.
    """
    p = Path(path)
    if not p.exists():
        if default_if_missing is _MISSING:
            raise FileNotFoundError(p)
        # Do NOT cache the synthetic default: a later `dump_yaml` may
        # create the file, and we want the next read to pick the real
        # content up. Caching the empty default here would mask that.
        return default_if_missing

    sig = _signature(p)
    if sig in _CACHE:
        return _CACHE[sig]

    # Drop any stale entries for this path (different mtime/size) so
    # the cache does not grow unboundedly when a file is rewritten many
    # times during one process lifetime (token store under load).
    path_str = sig[0]
    for stale_key in [k for k in _CACHE if k[0] == path_str and k != sig]:
        _CACHE.pop(stale_key, None)

    with p.open("r", encoding="utf-8") as f:
        # This module IS the cache; calling itself would recurse.
        data = yaml.safe_load(f)  # noqa: direct-yaml
    if data is None:
        data = {}
    _CACHE[sig] = data
    return data


def load_yaml(path, *, default_if_missing: Any = _MISSING) -> Dict[str, Any]:
    """Load a YAML file as a dict, memoised by absolute path.

    `default_if_missing` controls the missing-file behaviour:
    - Default (`_MISSING`): raise `FileNotFoundError` for callers that
      want to fail loud (resolution code).
    - Pass a value (typically `{}`): return that value when the file
      does not exist, mirroring the historical
      `cli.create.inventory.yaml_io.load_yaml` behaviour.

    Raises `ValueError` when the YAML root is not a mapping; use
    `load_yaml_any` for files whose root is a list or scalar.
    """
    data = _load_raw(path, default_if_missing=default_if_missing)
    if not isinstance(data, dict):
        raise ValueError(
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


def dump_yaml(path, data: Mapping[str, Any]) -> None:
    """Write `data` to `path` as YAML and evict the cached entry.

    The next `load_yaml(path)` will parse the just-written file (and
    cache the result), which is what callers expect when a CLI tool
    edits a file mid-run.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(  # noqa: direct-yaml — this module IS the cache.
            dict(data), f, sort_keys=False, default_flow_style=False
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
    return yaml.safe_dump(  # noqa: direct-yaml — this module IS the cache.
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
    return yaml.safe_load(text)  # noqa: direct-yaml — this module IS the cache.


def _drop_path(path) -> None:
    """Drop every cache entry that matches `path` (any mtime/size)."""
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


# Backwards-compatible alias for in-tree callers that may still reference
# the old name.
_reset_cache_for_tests = _reset
