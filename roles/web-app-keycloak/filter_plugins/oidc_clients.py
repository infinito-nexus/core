"""Keycloak clients that deployed applications declare for themselves.

An application that needs more than the one shared client declares them in its
own ``meta/services.yml``::

    services:
      sso:
        oidc:
          clients:
            webui: myapp-admin
            webmail: myapp-webmail

Keycloak converges whatever it finds, so no application id is named on this
side. The realm's built-in clients (``account``, ``broker``, ...) are not
declared by anybody and therefore never touched.
"""

from __future__ import annotations

from typing import Any


def _declared(app: Any) -> dict[str, Any]:
    if not isinstance(app, dict):
        return {}
    node: Any = app
    for key in ("services", "sso", "oidc", "clients"):
        if not isinstance(node, dict):
            return {}
        node = node.get(key)
    return node if isinstance(node, dict) else {}


def kc_declared_client_apps(applications: Any, app_ids: Any = None) -> list[str]:
    """Application ids (of the given ones) that declare their own clients.

    Each of these ships ``templates/keycloak/clients.json.j2`` — the realm
    import includes that fragment per app.

    Args:
        applications: the ``lookup('applications')`` map, application id -> config.
        app_ids: restrict to these ids; falsy means every application in the map.

    Returns:
        Sorted application ids with a non-empty ``services.sso.oidc.clients``.
    """
    if not isinstance(applications, dict):
        return []
    wanted = list(app_ids) if app_ids else list(applications)
    return sorted(a for a in wanted if _declared(applications.get(a)))


def kc_declared_client_ids(applications: Any, app_ids: Any = None) -> list[str]:
    """Every client id declared by the given applications, sorted and deduped.

    Args:
        applications: the ``lookup('applications')`` map, application id -> config.
        app_ids: restrict to these ids; falsy means every application in the map.

    Returns:
        Sorted unique client ids. Empty when nothing declares any.
    """
    if not isinstance(applications, dict):
        return []
    wanted = list(app_ids) if app_ids else list(applications)
    found: set[str] = set()
    for app_id in wanted:
        for value in _declared(applications.get(app_id)).values():
            if isinstance(value, str) and value.strip():
                found.add(value.strip())
    return sorted(found)


class FilterModule:
    def filters(self):
        return {
            "kc_declared_client_apps": kc_declared_client_apps,
            "kc_declared_client_ids": kc_declared_client_ids,
        }
