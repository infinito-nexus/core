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

A declared client may also carry client roles, each granted to one RBAC role
group of the declaring application::

    services:
      sso:
        oidc:
          client_roles:
            webui:
              admin: administrator
"""

from __future__ import annotations

from typing import Any

from utils.roles.applications.services.sso import get_sso_config

BACKCHANNEL_LOGOUT_URL = "backchannel.logout.url"


def _oidc_node(app: Any, key: str) -> dict[str, Any]:
    if not isinstance(app, dict):
        return {}
    node: Any = app
    for part in ("services", "sso", "oidc", key):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _declared(app: Any) -> dict[str, Any]:
    return _oidc_node(app, "clients")


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


def kc_declared_client_role_grants(
    applications: Any, app_ids: Any, group_root: str
) -> list[dict[str, str]]:
    """One grant per client role a declared client carries.

    Args:
        applications: the ``lookup('applications')`` map, application id -> config.
        app_ids: applications whose RBAC groups exist in this run.
        group_root: the RBAC group root name, ``RBAC.GROUP.NAME``.

    Returns:
        ``{client_id, role, group_path}`` dicts sorted by application, client
        key and role. A client key the application does not declare under
        ``services.sso.oidc.clients`` grants nothing, so a client that exists
        only in one mode carries its roles only in that mode.
    """
    if not isinstance(applications, dict):
        return []
    root = "/" + str(group_root).strip("/")
    grants = []
    for app_id in sorted(set(app_ids or [])):
        app = applications.get(app_id)
        clients = _declared(app)
        for key, roles in sorted(_oidc_node(app, "client_roles").items()):
            client_id = clients.get(key)
            if not isinstance(client_id, str) or not client_id.strip():
                continue
            if not isinstance(roles, dict):
                continue
            grants.extend(
                {
                    "client_id": client_id.strip(),
                    "role": str(role),
                    "group_path": f"{root}/{app_id}/{rbac_role}",
                }
                for role, rbac_role in sorted(roles.items())
            )
    return grants


def kc_proxy_clients(applications: Any, app_ids: Any) -> list[dict[str, Any]]:
    """
    Args:
        applications: the ``lookup('applications')`` map, application id -> config.
        app_ids: the applications deployed in this run.

    Returns:
        ``{application_id, client_id, scopes}`` per oauth2-proxy gated
        application that declares ``services.sso.oauth2.client``, sorted by
        application id.
    """
    if not isinstance(applications, dict):
        return []
    clients = []
    for app_id in sorted(set(app_ids or [])):
        if app_id not in applications:
            continue
        sso = get_sso_config(applications, app_id)
        if sso["is_proxy_gated"] and sso["oauth2_client"]:
            clients.append(
                {
                    "application_id": app_id,
                    "client_id": sso["oauth2_client"]["id"],
                    "scopes": sso["oauth2_client"]["scopes"],
                }
            )
    return clients


def kc_backchannel_logout_urls(clients: Any) -> list[str]:
    """Every back-channel logout URL the given clients carry, sorted and deduped.

    Args:
        clients: Keycloak client representations, as the realm dictionary lists them.

    Returns:
        Sorted unique URLs. Empty when no client receives logout tokens.
    """
    if not isinstance(clients, list):
        return []
    found: set[str] = set()
    for client in clients:
        attributes = client.get("attributes") if isinstance(client, dict) else None
        if not isinstance(attributes, dict):
            continue
        url = attributes.get(BACKCHANNEL_LOGOUT_URL)
        if isinstance(url, str) and url.strip():
            found.add(url.strip())
    return sorted(found)


class FilterModule:
    def filters(self):
        return {
            "kc_backchannel_logout_urls": kc_backchannel_logout_urls,
            "kc_declared_client_apps": kc_declared_client_apps,
            "kc_declared_client_ids": kc_declared_client_ids,
            "kc_declared_client_role_grants": kc_declared_client_role_grants,
            "kc_proxy_clients": kc_proxy_clients,
        }
