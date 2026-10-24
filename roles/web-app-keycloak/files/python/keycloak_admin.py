"""Keycloak admin REST client shared by the scripts beside this module.

Exports:
    KeycloakError: an HTTP error status, naming method, path and status but never the body.
    container_credentials: the permanent admin read from ``/proc/<pid>/environ`` of the Keycloak container.
    Keycloak: client whose ``call`` paths are relative to ``/admin/realms/<realm>/``.
    ADMIN_ENV_KEYS: container environment keys of the permanent admin user and password.
    PAGE: page size of every paged listing.
    TOKEN_MARGIN: seconds before expiry at which the master realm token is renewed.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

ADMIN_ENV_KEYS = (
    "KEYCLOAK_PERMANENT_ADMIN_USERNAME",
    "KEYCLOAK_PERMANENT_ADMIN_PASSWORD",
)
PAGE = 500
TOKEN_MARGIN = 30


class KeycloakError(Exception):
    pass


def container_credentials(environ: Path) -> tuple[str, str]:
    """Return the admin user and password from the Keycloak container's environment.

    Args:
        environ: ``/proc/<pid>/environ`` of the Keycloak container.
    """
    with environ.open("rb") as handle:
        raw = handle.read()
    env = dict(item.split("=", 1) for item in raw.decode().split("\0") if "=" in item)
    user_key, password_key = ADMIN_ENV_KEYS
    return env[user_key], env[password_key]


class Keycloak:
    """Admin REST client that renews its master realm token before it expires.

    Args:
        url: Keycloak base URL.
        realm: realm every ``call`` path is relative to.
        user: master realm administrator.
        password: that administrator's password.
    """

    def __init__(self, url: str, realm: str, user: str, password: str) -> None:
        self.url = url.rstrip("/")
        self.realm = realm
        self._form = urllib.parse.urlencode(
            {
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": user,
                "password": password,
            }
        ).encode()
        self._lock = threading.Lock()
        self._token = ""
        self._expires = 0.0

    def _bearer(self) -> str:
        with self._lock:
            if time.monotonic() > self._expires - TOKEN_MARGIN:
                request = urllib.request.Request(  # noqa: S310 fixed local Keycloak origin
                    f"{self.url}/realms/master/protocol/openid-connect/token",
                    data=self._form,
                )
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 fixed local Keycloak origin
                    body = json.load(response)
                self._token = body["access_token"]
                self._expires = time.monotonic() + int(body["expires_in"])
            return f"Bearer {self._token}"

    def call(
        self, method: str, path: str, payload: object = None, timeout: int = 60
    ) -> tuple[object, str]:
        """Return the decoded body and the id the ``Location`` header names.

        Args:
            method: HTTP method.
            path: path below ``/admin/realms/<realm>/``.
            payload: JSON body, or None for none.
            timeout: seconds the request may take.
        """
        data = b"" if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(  # noqa: S310 fixed local Keycloak origin
            f"{self.url}/admin/realms/{self.realm}/{path}",
            data=data if method in ("POST", "PUT") else None,
            headers={
                "Authorization": self._bearer(),
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 fixed local Keycloak origin
                raw = response.read()
                location = response.headers.get("Location") or ""
        except urllib.error.HTTPError as error:
            raise KeycloakError(f"{method} {path}: HTTP {error.code}") from None
        return (json.loads(raw) if raw else None), location.rsplit("/", 1)[-1]

    def children(self, group_id: str) -> list[dict]:
        """Return every direct subgroup of a group, page by page.

        Args:
            group_id: the parent group.
        """
        found: list[dict] = []
        while True:
            query = urllib.parse.urlencode(
                {"first": len(found), "max": PAGE, "briefRepresentation": "true"}
            )
            page, _ = self.call("GET", f"groups/{group_id}/children?{query}")
            found.extend(page)
            if len(page) < PAGE:
                return found
