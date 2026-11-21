"""Keycloak admin REST client shared by the scripts beside this module.

Exports:
    KeycloakError: a failed call, naming method and path but never the body.
    KeycloakHTTPError: a KeycloakError carrying the HTTP status as ``status``.
    container_credentials: the permanent admin read from ``/proc/<pid>/environ`` of the Keycloak container.
    Keycloak: client whose ``call`` paths are relative to ``/admin/realms/<realm>/`` and ``admin`` paths to ``/admin/realms/``.
    ServiceAccount: a Keycloak client signed in by the client-credentials grant of a confidential client of its realm.
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


class KeycloakHTTPError(KeycloakError):
    """
    Args:
        method: HTTP method.
        path: path below ``/admin/realms/``.
        status: the HTTP status Keycloak answered.
    """

    def __init__(self, method: str, path: str, status: int) -> None:
        super().__init__(f"{method} {path}: HTTP {status}")
        self.status = status


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
        self._form = urllib.parse.urlencode(self._grant(user, password)).encode()
        self._lock = threading.Lock()
        self._token = ""
        self._expires = 0.0

    def _token_realm(self) -> str:
        return "master"

    def _grant(self, principal: str, credential: str) -> dict[str, str]:
        return {
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": principal,
            "password": credential,
        }

    def _bearer(self) -> str:
        with self._lock:
            if time.monotonic() > self._expires - TOKEN_MARGIN:
                token_realm = urllib.parse.quote(self._token_realm(), safe="")
                request = urllib.request.Request(  # noqa: S310 fixed local Keycloak origin
                    f"{self.url}/realms/{token_realm}/protocol/openid-connect/token",
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
        return self.admin(method, f"{self.realm}/{path}", payload, timeout)

    def admin(
        self, method: str, path: str, payload: object = None, timeout: int = 60
    ) -> tuple[object, str]:
        """Return the decoded body and the id the ``Location`` header names.

        Args:
            method: HTTP method.
            path: path below ``/admin/realms/``, starting with a realm name.
            payload: JSON body, or None for none.
            timeout: seconds the request may take.
        """
        data = b"" if payload is None else json.dumps(payload).encode()
        return self._send(method, path, data, "application/json", timeout)

    def submit(self, path: str, fields: dict[str, str]) -> tuple[object, str]:
        """
        Args:
            path: path below ``/admin/realms/<realm>/``, query included.
            fields: the form fields, sent form-encoded by POST.

        Returns:
            The decoded body and the id the ``Location`` header names.
        """
        data = urllib.parse.urlencode(fields).encode()
        return self._send(
            "POST",
            f"{self.realm}/{path}",
            data,
            "application/x-www-form-urlencoded",
            60,
        )

    def _send(
        self, method: str, path: str, data: bytes, content_type: str, timeout: int
    ) -> tuple[object, str]:
        request = urllib.request.Request(  # noqa: S310 fixed local Keycloak origin
            f"{self.url}/admin/realms/{path}",
            data=data if method in ("POST", "PUT") or data else None,
            headers={
                "Authorization": self._bearer(),
                "Content-Type": content_type,
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 fixed local Keycloak origin
                raw = response.read()
                location = response.headers.get("Location") or ""
        except urllib.error.HTTPError as error:
            raise KeycloakHTTPError(method, path.split("?", 1)[0], error.code) from None
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


class ServiceAccount(Keycloak):
    """
    Args:
        url: Keycloak base URL.
        realm: realm of the client and of every ``call`` path.
        client_id: the confidential client.
        secret: that client's secret.
    """

    def __init__(self, url: str, realm: str, client_id: str, secret: str) -> None:
        super().__init__(url, realm, client_id, secret)

    def _token_realm(self) -> str:
        return self.realm

    def _grant(self, principal: str, credential: str) -> dict[str, str]:
        return {
            "client_id": principal,
            "client_secret": credential,
            "grant_type": "client_credentials",
        }
