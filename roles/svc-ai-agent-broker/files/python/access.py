from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


class AccessError(RuntimeError):
    pass


class Keycloak:
    """
    Args:
        base_url: Keycloak base URL.
        realm: realm holding the platform users.
        username: master-realm administrator.
        password: its password.
        timeout: seconds per HTTP call.
    """

    def __init__(self, base_url, realm, username, password, timeout):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token = ""
        self._token_expiry = 0.0

    def _request(self, method, url, data=None, headers=None):
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - https:// base fixed by KEYCLOAK_URL
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - https:// base fixed by KEYCLOAK_URL
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode(errors="replace")
        except urllib.error.URLError as error:
            raise AccessError(
                f"Keycloak unreachable at {url}: {error.reason}"
            ) from error

    def _admin_token(self):
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        status, body = self._request(
            "POST",
            f"{self.base_url}/realms/master/protocol/openid-connect/token",
            data=urllib.parse.urlencode(
                {
                    "client_id": "admin-cli",
                    "grant_type": "password",
                    "username": self.username,
                    "password": self.password,
                }
            ).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200:
            raise AccessError(f"Keycloak admin token refused: {status}")
        self._token = body["access_token"]
        self._token_expiry = time.monotonic() + max(int(body["expires_in"]) - 30, 10)
        return self._token

    def _get(self, path, query):
        url = f"{self.base_url}/admin/realms/{self.realm}{path}?{urllib.parse.urlencode(query)}"
        status, body = self._request(
            "GET", url, headers={"Authorization": f"Bearer {self._admin_token()}"}
        )
        if status != 200:
            raise AccessError(f"Keycloak GET {path} -> {status}")
        return body

    def groups_of(self, email):
        users = self._get("/users", {"email": email.lower(), "exact": "true"})
        if len(users) != 1:
            return frozenset()
        return frozenset(
            group["path"]
            for group in self._get(
                f"/users/{users[0]['id']}/groups",
                {"briefRepresentation": "true", "max": "1000"},
            )
        )

    def allows(self, email, group_path):
        return bool(email) and group_path in self.groups_of(email)
