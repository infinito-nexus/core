"""Application-domain cache: defaults, merged lookup.

Owns `_APPLICATIONS_DEFAULTS_CACHE` and `_MERGED_APPLICATIONS_CACHE`; the
variants live in `utils.cache.variants`, the per-role base config in
`utils.cache.role_config`. Public API: `get_application_defaults`,
`get_variants`, `get_merged_applications`, `get_lazy_applications`. Strictly ansible-free at
import time so the GitHub Actions runner-host CLI path
(`cli.administration.deploy.development.init` -> `plan_dev_inventory_matrix` ->
`get_variants`) keeps working without ansible installed.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Any

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.roles.applications.mcp import derive_mcp_presence
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_VOLUMES,
)

from .base import (
    _RENDER_GUARD,
    _cache_key,
    _decrypt_ansible_encrypted_strings,
    _fingerprint_scope,
    _render_with_templar,
    _resolve_override_mapping,
    _resolve_roles_dir,
)
from .carrier import _carried_applications, merged_applications_cache_key
from .role_config import (
    _CANONICAL_VOLUMES_BY_ROLE,
    _build_role_base_config,
    _iter_application_role_dirs,
)
from .variants import (
    _VARIANT_OVERRIDES_ONLY_CACHE,
    _VARIANTS_CACHE,
    _build_variants,
    _load_variants_overrides,
    get_variant_overrides_only,
    get_variants,
    with_variants,
)
from .yaml import load_yaml_any as _load_yaml_any_cached

__all__ = [
    "_build_role_base_config",
    "_build_variants",
    "_load_variants_overrides",
    "get_application_defaults",
    "get_canonical_volumes",
    "get_lazy_applications",
    "get_merged_applications",
    "get_variant_overrides_only",
    "get_variants",
    "with_variants",
]

if TYPE_CHECKING:
    import os
    from pathlib import Path

_APPLICATIONS_DEFAULTS_CACHE: dict[str, dict[str, Any]] = {}
_MERGED_APPLICATIONS_CACHE: dict[tuple, Mapping[str, Any]] = {}

_UNRENDERED_FORMS_KEY = ROLE_FILE_META_FORMS.rsplit("/", 1)[-1].removesuffix(".yml")


def _build_application_defaults(roles_dir: Path) -> dict[str, Any]:
    """Return ``{application_id: base_config}``, each role's variant-free
    ``meta/<topic>.yml`` payload only. Variants stay accessible via
    :func:`get_variants`. Using variant 0 here would leak its service
    flags into variant-N consumers' runtime view via deep-merge."""
    defaults: dict[str, Any] = {}
    for role_dir in _iter_application_role_dirs(roles_dir):
        defaults[role_dir.name] = _build_role_base_config(role_dir, roles_dir)
    derive_mcp_presence(defaults)
    return {key: defaults[key] for key in sorted(defaults)}


def get_application_defaults(
    *, roles_dir: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    key = _cache_key(resolved_roles_dir)
    cached = _APPLICATIONS_DEFAULTS_CACHE.get(key)
    if cached is None:
        cached = _build_application_defaults(resolved_roles_dir)
        _APPLICATIONS_DEFAULTS_CACHE[key] = cached
    return copy.deepcopy(cached)


_POST_RENDER_KEYS: frozenset[str] = frozenset({"volumes", _UNRENDERED_FORMS_KEY})

KeyPaths = tuple[tuple[str, ...], ...]


def _select(config: Mapping[str, Any], paths: KeyPaths) -> tuple[dict[str, Any], bool]:
    """
    Args:
        config: one application, rendered or not.
        paths: key paths to keep; a path ends at its first missing key.

    Returns:
        The selected tree and whether it is exact. It is not exact when a
        path meets a non-mapping before its last key: that value is kept
        whole, as a reader of the full application would see it.
    """
    selected: dict[str, Any] = {}
    exact = True
    for path in paths:
        node: Any = config
        target = selected
        for depth, key in enumerate(path):
            if key not in node:
                break
            node = node[key]
            if depth == len(path) - 1:
                target[key] = node
                break
            if not isinstance(node, Mapping):
                target[key] = node
                exact = False
                break
            child = target.get(key)
            if child is node:
                break
            if child is None:
                child = target[key] = {}
            target = child
    return selected, exact


class LazyApplications(Mapping[str, Any]):
    """Exception: an application renders on its first read against the
    variables and templar variables of the call that created the payload,
    not of the call that first reads it.
    """

    def __init__(
        self,
        cache_key: tuple,
        merged: dict[str, Any],
        *,
        variables: Mapping[str, Any],
        roles_dir: str | os.PathLike[str] | None,
        templar: Any,
    ) -> None:
        """
        Args:
            cache_key: the key this payload is cached under.
            merged: role defaults merged with the inventory overrides.
            variables: the variables scope of the creating call.
            roles_dir: the roles tree as the creating call passed it.
            templar: the templar to render with; ``None`` renders nothing.
        """
        from .users import get_merged_users

        self._key = cache_key
        self._templar = templar
        self._variables = dict(variables)
        available = getattr(templar, "available_variables", None)
        self._available = dict(available) if available else available
        self._view = _decrypt_ansible_encrypted_strings(merged)
        for config in merged.values():
            if isinstance(config, dict):
                config.pop("volumes", None)
        self._forms = {
            app_id: config.pop(_UNRENDERED_FORMS_KEY)
            for app_id, config in merged.items()
            if isinstance(config, dict) and _UNRENDERED_FORMS_KEY in config
        }
        self._merged = merged
        with self._guard():
            self._users = get_merged_users(
                variables=variables, roles_dir=roles_dir, templar=None
            )
        self._volumes = {app_id: get_canonical_volumes(app_id) for app_id in merged}
        self._rendered: dict[str, Any] = {}
        self._busy: set[str] = set()
        self._full: dict[str, Any] | None = None
        self._views: dict[KeyPaths, dict[str, Any]] = {}

    @contextlib.contextmanager
    def _guard(self) -> Iterator[None]:
        flag = getattr(_RENDER_GUARD, "applications", False)
        payloads = getattr(_RENDER_GUARD, "nested_payloads", {})
        keys = getattr(_RENDER_GUARD, "rendering_keys", ())
        _RENDER_GUARD.applications = True
        _RENDER_GUARD.nested_payloads = {self._key: self._view}
        _RENDER_GUARD.rendering_keys = (*keys, self._key)
        try:
            yield
        finally:
            _RENDER_GUARD.applications = flag
            _RENDER_GUARD.nested_payloads = payloads if flag else {}
            _RENDER_GUARD.rendering_keys = keys

    def _render(self, value: Any, application_id: str) -> Any:
        templar = self._templar
        swap = templar is not None and hasattr(templar, "available_variables")
        if swap:
            current = templar.available_variables
            templar.available_variables = self._available
        try:
            return _render_with_templar(
                value,
                templar=templar,
                variables={**self._variables, "application_id": application_id},
                raw_applications=self._merged,
                raw_users=self._users,
            )
        finally:
            if swap:
                templar.available_variables = current

    def _render_applications(self, application_ids: list[str]) -> None:
        pending = [a for a in application_ids if a not in self._rendered]
        if not pending:
            return
        reentered = self._busy.intersection(pending)
        if reentered:
            raise RuntimeError(
                f"applications: {sorted(reentered)} read while rendering itself"
            )
        rendered: dict[str, Any] = {}
        with _fingerprint_scope(), self._guard():
            for app_id in pending:
                if app_id in self._rendered:
                    continue
                self._busy.add(app_id)
                try:
                    rendered[app_id] = self._render(self._merged[app_id], app_id)
                finally:
                    self._busy.discard(app_id)
        for app_id, config in rendered.items():
            if not isinstance(config, dict):
                continue
            if self._volumes.get(app_id):
                config["volumes"] = copy.deepcopy(self._volumes[app_id])
            if app_id in self._forms:
                config[_UNRENDERED_FORMS_KEY] = copy.deepcopy(self._forms[app_id])
        self._rendered.update(rendered)

    def materialize(self) -> dict[str, Any]:
        """
        Returns:
            The same dict on every call, in the order of the merged payload.
        """
        if self._full is None:
            self._render_applications(list(self._merged))
            self._full = {app_id: self._rendered[app_id] for app_id in self._merged}
        return self._full

    def view(self, paths: KeyPaths) -> dict[str, Any]:
        """
        Args:
            paths: key paths to keep per application, e.g.
                ``(("domains",), ("services", "tor"))``.

        Returns:
            ``{application_id: selected parts}``, cached per *paths*.
        """
        cached = self._views.get(paths)
        if cached is not None:
            return cached
        cuttable = not any(path and path[0] in _POST_RENDER_KEYS for path in paths)
        selected: dict[str, dict[str, Any]] = {}
        whole: list[str] = []
        for app_id, config in self._merged.items():
            if app_id in self._rendered:
                continue
            if cuttable and isinstance(config, Mapping):
                parts, exact = _select(config, paths)
                if exact:
                    selected[app_id] = parts
                    continue
            whole.append(app_id)
        self._render_applications(whole)
        with _fingerprint_scope(), self._guard():
            rendered = {
                app_id: self._render(parts, app_id)
                for app_id, parts in selected.items()
            }
        view: dict[str, Any] = {}
        for app_id in self._merged:
            if app_id in rendered:
                view[app_id] = rendered[app_id]
                continue
            config = self._rendered[app_id]
            view[app_id] = (
                _select(config, paths)[0] if isinstance(config, Mapping) else config
            )
        self._views[paths] = view
        return view

    def __getitem__(self, application_id: str) -> Any:
        if application_id not in self._rendered:
            if application_id not in self._merged:
                raise KeyError(application_id)
            self._render_applications([application_id])
        return self._rendered[application_id]

    def __contains__(self, application_id: object) -> bool:
        return application_id in self._merged

    def __iter__(self) -> Iterator[str]:
        return iter(self._merged)

    def __len__(self) -> int:
        return len(self._merged)

    def __repr__(self) -> str:
        return repr(self.materialize())

    def __copy__(self) -> dict[str, Any]:
        return dict(self.materialize())

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        return copy.deepcopy(self.materialize(), memo)

    def __reduce__(self) -> tuple:
        return (dict, (self.materialize(),))


def get_lazy_applications(
    *,
    variables: Mapping[str, Any] | None = None,
    roles_dir: str | os.PathLike[str] | None = None,
    templar: Any = None,
) -> Mapping[str, Any]:
    """Return the applications payload for *variables*, rendering nothing yet.

    A re-entrant call for the key being rendered returns the unrendered
    payload, memoised on the render guard with every vault value decrypted,
    so a nested lookup reads the same plaintext credential.

    Args:
        variables: the variables scope; only the parts the cache key reads
            and the ``applications`` overrides shape the payload.
        roles_dir: roles tree to build from, defaulting to the project's own.
        templar: the templar to render with; ``None`` renders nothing.

    Returns:
        The carried payload when the carrier key matches, the unrendered
        payload inside a render of the same key, else the cached
        :class:`LazyApplications` of the key.
    """
    variables = variables or {}
    resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir)
    cache_key = merged_applications_cache_key(variables, roles_dir=resolved_roles_dir)
    nested = getattr(_RENDER_GUARD, "applications", False)
    in_render = nested and cache_key in getattr(_RENDER_GUARD, "rendering_keys", ())
    cached = None if in_render else _MERGED_APPLICATIONS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    carried = _carried_applications(variables, cache_key)
    if carried is not None:
        _MERGED_APPLICATIONS_CACHE.setdefault(cache_key, carried)
        return carried

    if nested:
        carried_nested = getattr(_RENDER_GUARD, "nested_payloads", {}).get(cache_key)
        if carried_nested is not None:
            return carried_nested

    defaults = get_application_defaults(roles_dir=resolved_roles_dir)

    overrides = _resolve_override_mapping(variables, "applications", templar=templar)

    merged = merge_with_defaults(defaults, overrides)

    if nested:
        payloads = getattr(_RENDER_GUARD, "nested_payloads", None)
        if payloads is None:
            payloads = _RENDER_GUARD.nested_payloads = {}
        payloads[cache_key] = _decrypt_ansible_encrypted_strings(merged)
        return payloads[cache_key]

    applications = LazyApplications(
        cache_key,
        merged,
        variables=variables,
        roles_dir=roles_dir,
        templar=templar,
    )
    _MERGED_APPLICATIONS_CACHE[cache_key] = applications
    return applications


def get_merged_applications(
    *,
    variables: dict[str, Any] | None = None,
    roles_dir: str | os.PathLike[str] | None = None,
    templar: Any = None,
    paths: KeyPaths | None = None,
) -> dict[str, Any]:
    """Return the rendered applications payload for *variables*, cached per key.

    ``forms`` and ``volumes`` stay unrendered; each application renders with
    ``application_id`` bound to its own id.

    Args:
        variables: the variables scope, see `get_lazy_applications`.
        roles_dir: roles tree to build from, defaulting to the project's own.
        templar: the templar to render with; ``None`` renders nothing.
        paths: key paths to return per application instead of the whole
            payload; ``None`` returns everything.

    Returns:
        The same dict for every call with one key, or the unrendered payload
        when called from inside a render of that key.
    """
    applications = get_lazy_applications(
        variables=variables, roles_dir=roles_dir, templar=templar
    )
    if not isinstance(applications, LazyApplications):
        return applications
    if paths is None:
        return applications.materialize()
    return applications.view(paths)


def get_canonical_volumes(application_id: str) -> dict[str, Any]:
    """Return the canonical dict-of-dicts `meta/volumes.yml` for *application_id*.

    Lives outside the applications payload so its embedded Jinja `source:`
    strings stay raw — see the `_CANONICAL_VOLUMES_BY_ROLE` doc-comment.

    An empty result is cached under its id too, or a role without the file
    would re-stat it on every call.
    """
    cached = _CANONICAL_VOLUMES_BY_ROLE.get(application_id)
    if cached is not None:
        return cached

    data = _load_yaml_any_cached(
        _resolve_roles_dir(roles_dir=None) / application_id / ROLE_FILE_META_VOLUMES,
        default_if_missing={},
    )
    volumes = data if isinstance(data, dict) else {}
    _CANONICAL_VOLUMES_BY_ROLE[application_id] = volumes
    return volumes


def _reset() -> None:
    from plugins.lookup.application_gid import _discover_sorted_application_ids

    _APPLICATIONS_DEFAULTS_CACHE.clear()
    _VARIANTS_CACHE.clear()
    _VARIANT_OVERRIDES_ONLY_CACHE.clear()
    _MERGED_APPLICATIONS_CACHE.clear()
    _CANONICAL_VOLUMES_BY_ROLE.clear()
    _discover_sorted_application_ids.cache_clear()
