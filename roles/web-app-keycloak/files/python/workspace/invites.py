from __future__ import annotations

import http.client
import json
import re
import ssl
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

from organization import ROLES
from workspaces import INVITE_PREFIX, PENDING_PREFIX, Workspace

if TYPE_CHECKING:
    from collections.abc import Callable

    from keycloak_admin import ServiceAccount

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INVITE_PATH = "/v1/platform/data/store/invites/{workspace}/{key}"


def invitations(kc: ServiceAccount, ws: Workspace, **query: str) -> list[dict]:
    """
    Args:
        kc: client.
        ws: the workspace.
        **query: filters of the invitation listing, such as ``email`` and ``status``.

    Returns:
        The invitations of the organization Keycloak holds, at most one page.
    """
    params = urllib.parse.urlencode({**query, "first": 0, "max": 100})
    found, _ = kc.call("GET", f"{ws.base}/invitations?{params}")
    return found


def write_attributes(
    kc: ServiceAccount, ws: Workspace, edit: Callable[[dict], None]
) -> None:
    """
    Args:
        kc: client.
        ws: the workspace, whose organization follows the write.
        edit: changes the attribute map of the organization read in this call,
            which then goes back whole, marker included.
    """
    org, _ = kc.call("GET", ws.base)
    attributes = org.get("attributes") or {}
    edit(attributes)
    org["attributes"] = attributes
    kc.call("PUT", ws.base, org)
    ws.org = org


def drop_key(attributes: dict, key: str) -> None:
    """
    Args:
        attributes: an organization's attribute map, changed in place.
        key: the invitation key whose pending listing and address are removed.
    """
    attributes.pop(INVITE_PREFIX + key, None)
    for role in ROLES:
        name = PENDING_PREFIX + role
        if key in attributes.get(name, []):
            attributes[name] = [k for k in attributes[name] if k != key]
            if not attributes[name]:
                del attributes[name]


def record_key(attributes: dict, key: str, role: str, address: str) -> None:
    """
    Args:
        attributes: an organization's attribute map, changed in place.
        key: the invitation key.
        role: the role group the invitee joins once placed.
        address: the invitee's address.
    """
    drop_key(attributes, key)
    attributes[PENDING_PREFIX + role] = [
        *attributes.get(PENDING_PREFIX + role, []),
        key,
    ]
    attributes[INVITE_PREFIX + key] = [address]


def staged(env: dict, workspace: str, key: str) -> tuple[str, str]:
    """
    Args:
        env: the task environment with BAO_ADDR and BAO_TOKEN_FILE, and under
            ``TLS_MODE`` ``self_signed`` BAO_CACERT, the deployment CA trusted
            beside the system store.
        workspace: the workspace id.
        key: the invitation key.

    Returns:
        The address and role the store staged under
        ``platform/data/store/invites/<workspace>/<key>``.
    """
    url = urllib.parse.urlsplit(env["BAO_ADDR"])
    if url.scheme != "https" or not url.hostname:
        raise ValueError("BAO_ADDR is not an https URL")
    token = Path(env["BAO_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    context = ssl.create_default_context(cafile=env.get("BAO_CACERT") or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = http.client.HTTPSConnection(
        url.hostname, url.port or 443, timeout=30, context=context
    )
    try:
        connection.request(
            "GET",
            url.path.rstrip("/") + INVITE_PATH.format(workspace=workspace, key=key),
            headers={"X-Vault-Token": token},
        )
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    if response.status != 200:
        raise ValueError(
            f"OpenBao answered {response.status} for the staged invitation {key}"
        )
    data = json.loads(body)["data"]["data"]
    address = str(data["email"]).strip().lower()
    if not EMAIL.match(address):
        raise ValueError(f"the staged invitation {key} holds no valid address")
    if data["role"] not in ROLES:
        raise ValueError(f"the staged invitation {key} names no workspace role")
    return address, data["role"]
