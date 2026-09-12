from __future__ import annotations


def _entity_name(role: str) -> str:
    return role.rsplit("-", 1)[-1]


def _const_lookup_config(**values):
    def _lookup(_app, path, default):
        return values.get(path, default)

    return _lookup


def _role_lookup_config(per_role, **values):
    """Answer per (role, path) so a provider override is expressible.

    Args:
        per_role: ``{role: {path: value}}`` consulted before the shared map.
        values: paths every role answers identically.

    An unset path is answered the way utils.roles.applications.config.get does
    it, which turns a ``None`` default into ``False``.
    """

    def _lookup(app, path, default):
        scoped = per_role.get(app) or {}
        if path in scoped:
            return scoped[path]
        if path in values:
            return values[path]
        return default if default is not None else False

    return _lookup


def _const_lookup_database(**values):
    def _lookup(_app, key):
        return values.get(key, "")

    return _lookup


def _database(local):
    def _lookup(_app, key):
        return {"local": local}.get(key, "")

    return _lookup
