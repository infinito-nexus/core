from __future__ import annotations

import http.client
import json
import re
import ssl
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from utils.tls.client import https_connection, tls_context

REFERENCE_KEY = "openbao"
ADDR_ENV = "BAO_ADDR"
LOGIN_ENV = "BAO_TOKEN"
CACERT_ENV = "BAO_CACERT"
ROLE_ENV = "BAO_ROLE"
PROXY_ENV = "EGRESS_PROXY"
TASK_JWT_ENV = "SEMAPHORE_JWT"
TASK_LOGIN_MOUNT = "jwt"
CREDENTIALS_PATH = ("secrets", "credentials")
USERS_KEY = "users"
USER_REFERENCE_FIELDS = ("password", "email", "firstname", "lastname")
MAILBOX_POLICY_MOVED_EMAIL_FIELD = "secondary_email"
TIMEOUT_SECONDS = 30
_SEGMENT = r"[A-Za-z0-9_@+=,.-]+"
_REFERENCE = re.compile(
    rf"(?P<mount>[a-z0-9][a-z0-9_-]*)/(?P<path>{_SEGMENT}(?:/{_SEGMENT})*)#(?P<field>[A-Za-z0-9_.-]+)"
)


class OpenBaoError(Exception):
    pass


@dataclass(frozen=True)
class Reference:
    mount: str
    path: str
    field: str

    def __str__(self) -> str:
        return f"{self.mount}/{self.path}#{self.field}"


def parse_reference(value: Any, credential: str) -> Reference | None:
    """
    Args:
        value: a credential leaf as the inventory holds it.
        credential: the credential's dotted name, named in every refusal.

    Returns:
        The reference the leaf holds, or None for any other value.
    """
    if not isinstance(value, Mapping) or REFERENCE_KEY not in value:
        return None
    if len(value) != 1:
        raise OpenBaoError(
            f"credential {credential}: an OpenBao reference holds the single key "
            f"'{REFERENCE_KEY}', not {sorted(str(key) for key in value)}"
        )
    target = value[REFERENCE_KEY]
    match = _REFERENCE.fullmatch(target) if isinstance(target, str) else None
    if match is None or any(part in (".", "..") for part in match["path"].split("/")):
        raise OpenBaoError(
            f"credential {credential}: an OpenBao reference reads <mount>/<path>#<field>"
        )
    return Reference(**match.groupdict())


def references(credentials: Any, prefix: str = "") -> Iterator[tuple[str, Reference]]:
    """
    Args:
        credentials: a ``secrets.credentials`` mapping of one application.
        prefix: the dotted name of ``credentials`` itself.

    Returns:
        Each reference below it with the credential's dotted name.
    """
    if not isinstance(credentials, Mapping):
        return
    for key, value in credentials.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        reference = parse_reference(value, name)
        if reference is not None:
            yield name, reference
        elif isinstance(value, Mapping):
            yield from references(value, name)


class OpenBaoClient:
    def __init__(
        self,
        addr: str,
        cafile: str | None,
        token: str | None,
        proxy: str | None = None,
    ) -> None:
        """
        Args:
            addr: the platform's OpenBao, an ``https://`` URL.
            cafile: see ``tls_context``.
            token: the OpenBao token every read and write carries.
            proxy: see ``https_connection``.
        """
        parts = urlsplit(addr)
        if parts.scheme != "https" or not parts.hostname:
            raise OpenBaoError(f"{ADDR_ENV} must be an https:// URL")
        self._host = parts.hostname
        self._port = parts.port or 443
        self._prefix = parts.path.rstrip("/")
        self._context = tls_context(cafile)
        self._proxy = proxy
        self.token = token
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}

    def request(
        self, method: str, path: str, body: Mapping[str, Any] | None
    ) -> tuple[int, dict[str, Any]]:
        """
        Args:
            method: the HTTP method.
            path: the API path below ``/v1/``.
            body: the JSON body, or None.

        Returns:
            The HTTP status and the JSON object of the answer, empty when none.
        """
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-Vault-Token"] = self.token
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        connection = https_connection(
            self._host, self._port, self._context, TIMEOUT_SECONDS, self._proxy
        )
        try:
            connection.request(
                method, f"{self._prefix}/v1/{path}", body=payload, headers=headers
            )
            response = connection.getresponse()
            raw = response.read()
        except ssl.SSLError as exc:
            raise OpenBaoError(
                f"OpenBao at {self._host}: TLS verification failed ({exc.reason})"
            ) from None
        except (OSError, http.client.HTTPException) as exc:
            raise OpenBaoError(
                f"OpenBao at {self._host} is unreachable ({type(exc).__name__})"
            ) from None
        finally:
            connection.close()
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return response.status, data if isinstance(data, dict) else {}

    def login_jwt(self, mount: str, role: str, jwt: str) -> str:
        """
        Args:
            mount: the ``jwt`` auth mount the role lives in.
            role: the role the task logs in to.
            jwt: the task's own token.

        Returns:
            The OpenBao token of the login, also kept for later requests.
        """
        status, data = self.request(
            "POST", f"auth/{quote(mount)}/login", {"role": role, "jwt": jwt}
        )
        token = (data.get("auth") or {}).get("client_token")
        if status != 200 or not token:
            raise OpenBaoError(
                f"OpenBao refused the task token login to auth/{mount} role {role} (HTTP {status})"
            )
        self.token = token
        return token

    def _data(self, mount: str, path: str) -> dict[str, Any]:
        key = (mount, path)
        if key not in self._cache:
            status, body = self.request(
                "GET", f"{quote(mount)}/data/{quote(path)}", None
            )
            if status == 404:
                raise OpenBaoError(f"{mount}/{path} does not exist (HTTP 404)")
            if status == 403:
                raise OpenBaoError(f"{mount}/{path} is denied to this login (HTTP 403)")
            if status != 200:
                raise OpenBaoError(f"{mount}/{path} is unreadable (HTTP {status})")
            self._cache[key] = (body.get("data") or {}).get("data") or {}
        return self._cache[key]

    def read_all(self, mount: str, path: str) -> dict[str, Any]:
        return dict(self._data(mount, path))

    def list_tree(self, mount: str, prefix: str) -> list[str]:
        """
        Args:
            mount: a KV v2 mount.
            prefix: a folder below it, ending with ``/``.

        Returns:
            The path of every secret below the folder, relative to it.
        """
        status, body = self.request(
            "GET", f"{quote(mount)}/metadata/{quote(prefix)}?list=true", None
        )
        if status == 404:
            return []
        if status != 200:
            raise OpenBaoError(f"{mount}/{prefix} cannot be listed (HTTP {status})")
        found: list[str] = []
        for key in (body.get("data") or {}).get("keys") or []:
            if key.endswith("/"):
                found.extend(
                    key + child for child in self.list_tree(mount, prefix + key)
                )
            else:
                found.append(key)
        return found

    def read(self, reference: Reference) -> Any:
        try:
            data = self._data(reference.mount, reference.path)
        except OpenBaoError as exc:
            raise OpenBaoError(f"{exc}; field {reference.field}") from None
        if reference.field not in data:
            raise OpenBaoError(
                f"{reference.mount}/{reference.path} holds no field {reference.field}"
            )
        return data[reference.field]

    def write_create_only(self, mount: str, path: str, data: Mapping[str, Any]) -> bool:
        """
        Args:
            mount: a KV v2 mount.
            path: the secret's path below the mount.
            data: the fields of the new secret.

        Returns:
            True when the secret was written, False when it already existed and
            kept every version unchanged.
        """
        status, body = self.request(
            "POST",
            f"{quote(mount)}/data/{quote(path)}",
            {"options": {"cas": 0}, "data": dict(data)},
        )
        if status == 200:
            return True
        errors = " ".join(str(error) for error in body.get("errors") or [])
        if status == 400 and "check-and-set" in errors:
            return False
        raise OpenBaoError(f"{mount}/{path} could not be created (HTTP {status})")

    def write(self, mount: str, path: str, data: Mapping[str, Any]) -> None:
        """
        Args:
            mount: a KV v2 mount.
            path: the secret's path below the mount.
            data: the fields of the secret's new version, which replaces
                every field of the one before.
        """
        status, _ = self.request(
            "POST", f"{quote(mount)}/data/{quote(path)}", {"data": dict(data)}
        )
        if status not in (200, 204):
            raise OpenBaoError(f"{mount}/{path} could not be written (HTTP {status})")


def login(environ: Mapping[str, str]) -> OpenBaoClient:
    """
    Args:
        environ: the controller's environment: ``BAO_ADDR``, optionally
            ``BAO_CACERT`` and ``EGRESS_PROXY`` (a workspace or export
            runner), and either ``SEMAPHORE_JWT`` with ``BAO_ROLE`` (a
            Semaphore task) or ``BAO_TOKEN`` (an operator).

    Returns:
        A client of ``BAO_ADDR`` holding the run's one token: a task token
        login when the task token and role are set, else the operator token.
    """
    addr = environ.get(ADDR_ENV, "")
    if not addr:
        raise OpenBaoError(f"{ADDR_ENV} names no OpenBao")
    client = OpenBaoClient(
        addr,
        environ.get(CACERT_ENV) or None,
        None,
        proxy=environ.get(PROXY_ENV) or None,
    )
    task_token = environ.get(TASK_JWT_ENV, "")
    role = environ.get(ROLE_ENV, "")
    if task_token and role:
        client.login_jwt(TASK_LOGIN_MOUNT, role, task_token)
        return client
    operator_token = environ.get(LOGIN_ENV, "")
    if operator_token:
        client.token = operator_token
        return client
    raise OpenBaoError(
        f"no OpenBao login: set {TASK_JWT_ENV} with {ROLE_ENV} (a Semaphore task) "
        f"or {LOGIN_ENV} (an operator)"
    )


_SESSION: dict[str, OpenBaoClient] = {}


def session_client(environ: Mapping[str, str]) -> OpenBaoClient:
    """
    Args:
        environ: the controller's environment, holding ``BAO_ADDR``,
            ``BAO_TOKEN``, under ``self_signed`` ``BAO_CACERT`` and, on a
            workspace or export runner, ``EGRESS_PROXY``.

    Returns:
        One client per process, so a value is fetched once per run.
    """
    addr = environ.get(ADDR_ENV, "")
    token = environ.get(LOGIN_ENV, "")
    if not addr or not token:
        raise OpenBaoError(
            f"an OpenBao reference needs {ADDR_ENV} and the login of the deploy in {LOGIN_ENV}"
        )
    proxy = environ.get(PROXY_ENV) or None
    key = f"{addr}\0{environ.get(CACERT_ENV, '')}\0{token}\0{proxy or ''}"
    if key not in _SESSION:
        _SESSION.clear()
        _SESSION[key] = OpenBaoClient(
            addr, environ.get(CACERT_ENV) or None, token, proxy=proxy
        )
    return _SESSION[key]


def _under_credentials(parts: tuple[str, ...]) -> bool:
    depth = min(len(parts), len(CREDENTIALS_PATH))
    return parts[:depth] == CREDENTIALS_PATH[:depth]


def resolve(
    value: Any, config_path: str, application_id: str, environ: Mapping[str, str]
) -> Any:
    """
    Args:
        value: what ``lookup('config', application_id, config_path)`` fetched.
        config_path: the dotted path the lookup was asked for.
        application_id: the application, named in every failure.
        environ: see ``session_client``.

    Returns:
        The value with every OpenBao reference below ``secrets.credentials``
        replaced by the field it names; any other value unchanged.
    """
    parts = tuple(part for part in config_path.split(".") if part)
    resolved, _ = _resolve(value, parts, application_id, environ)
    return resolved


def _resolve(
    node: Any,
    parts: tuple[str, ...],
    application_id: str,
    environ: Mapping[str, str],
) -> tuple[Any, bool]:
    if not _under_credentials(parts):
        return node, False
    if len(parts) > len(CREDENTIALS_PATH):
        name = f"{application_id}.{'.'.join(parts)}"
        reference = parse_reference(node, name)
        if reference is not None:
            try:
                return session_client(environ).read(reference), True
            except OpenBaoError as exc:
                raise OpenBaoError(f"credential {name}: {exc}") from None
    if not isinstance(node, Mapping):
        return node, False
    changed = False
    resolved: dict[Any, Any] = {}
    for key, child in node.items():
        resolved[key], child_changed = _resolve(
            child, (*parts, str(key)), application_id, environ
        )
        changed = changed or child_changed
    return (resolved if changed else node), changed


def _collect_user_references(
    node: Any, parts: tuple[str, ...], found: list[tuple[tuple[str, ...], Reference]]
) -> None:
    if len(parts) > 1:
        name = ".".join(parts)
        reference = parse_reference(node, name)
        if reference is not None:
            if len(parts) != 3 or parts[2] not in (
                *USER_REFERENCE_FIELDS,
                MAILBOX_POLICY_MOVED_EMAIL_FIELD,
            ):
                raise OpenBaoError(
                    f"{name}: only the {', '.join(USER_REFERENCE_FIELDS)} fields of "
                    "users.<name> may hold an OpenBao reference"
                )
            found.append((parts, reference))
            return
    if isinstance(node, Mapping):
        for key, child in node.items():
            _collect_user_references(child, (*parts, str(key)), found)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _collect_user_references(child, (*parts, str(index)), found)


def user_references(
    value: Any, path: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Reference]]:
    """
    Args:
        value: what ``users.<path>`` holds: the whole users mapping for ``()``,
            one user for ``(<name>,)`` or a field of one below it.
        path: the keys below ``users`` that lead to ``value``.

    Returns:
        The full key path and the reference of every ``users.<name>.<field>``
        of ``USER_REFERENCE_FIELDS`` below ``value`` that holds an OpenBao
        reference; any other users field holding one is refused with its
        dotted name.
    """
    found: list[tuple[tuple[str, ...], Reference]] = []
    _collect_user_references(value, (USERS_KEY, *path), found)
    return found


CLEAN_USERS_LIMIT = 4096
_CLEAN_USERS: dict[tuple[int, tuple[str, ...]], Any] = {}


def _replace(node: Any, keys: tuple[str, ...], value: Any) -> Any:
    if not keys:
        return value
    return {**node, keys[0]: _replace(node[keys[0]], keys[1:], value)}


def resolve_users(value: Any, path: tuple[str, ...], environ: Mapping[str, str]) -> Any:
    """
    Args:
        value: see ``user_references``.
        path: see ``user_references``.
        environ: see ``session_client``.

    Returns:
        ``value`` with the reference of every ``users.<name>.<field>`` of
        ``USER_REFERENCE_FIELDS`` below it replaced by the field it names;
        ``value`` itself when it holds none.
    """
    key = (id(value), path)
    if _CLEAN_USERS.get(key) is value:
        return value
    found = user_references(value, path)
    if not found:
        if len(_CLEAN_USERS) >= CLEAN_USERS_LIMIT:
            _CLEAN_USERS.clear()
        _CLEAN_USERS[key] = value
        return value
    resolved = value
    for parts, reference in found:
        name = ".".join(parts)
        try:
            secret = session_client(environ).read(reference)
        except OpenBaoError as exc:
            raise OpenBaoError(f"credential {name}: {exc}") from None
        resolved = _replace(resolved, parts[1 + len(path) :], secret)
    return resolved
