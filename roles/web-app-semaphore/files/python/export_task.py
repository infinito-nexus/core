from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import smtplib
import urllib.parse
from collections.abc import Callable, Mapping
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from utils.openbao_client import (
    OpenBaoClient,
    OpenBaoError,
    https_connection,
    tls_context,
)

if TYPE_CHECKING:
    import socket
    import ssl

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
MEMBERSHIP_TYPE = "ORGANIZATION_GROUP_MEMBERSHIP"
LOGIN_MOUNT = "jwt-export"
PLATFORM_MOUNT = "platform"
KEYCLOAK_LOGIN_PATH = "export/keycloak"
MAIL_LOGIN_PATH = "export/mail"
S3_LOGIN_PATH = "export/s3"
OWNERS_PATH = "export/owners/"
BUCKET = "exports"
DAY_MS = 86_400_000
MAIL_FLAGS = ("EXPORT_MAIL_TLS", "EXPORT_MAIL_AUTH")
PROXY_ENV = "EGRESS_PROXY"
LOGIN_ENV = ("SEMAPHORE_JWT", "BAO_ADDR")
KEYCLOAK_ENV = ("EXPORT_KEYCLOAK_URL", "EXPORT_KEYCLOAK_REALM")
MAIL_ENV = ("EXPORT_MAIL_HOST", "EXPORT_MAIL_PORT", "EXPORT_MAIL_FROM", *MAIL_FLAGS)
S3_ENV = ("EXPORT_S3_ENDPOINT", "EXPORT_S3_REGION")

Opener = Callable[[str, str, bytes | None, Mapping[str, str]], tuple[int, bytes]]


class ExportRefusedError(Exception):
    pass


FAILURES = (ExportRefusedError, OpenBaoError, OSError, smtplib.SMTPException)


def reason(exc: BaseException) -> str:
    """
    Args:
        exc: one of ``FAILURES``.

    Returns:
        The message of a refusal, else only the name of the error, which may
        carry a request or a reply.
    """
    if isinstance(exc, (ExportRefusedError, OpenBaoError)):
        return str(exc)
    return type(exc).__name__


class TunneledSMTP(smtplib.SMTP):
    def __init__(
        self, proxy: str, host: str, port: int, context: ssl.SSLContext | None
    ) -> None:
        """
        Args:
            proxy: ``<name>:<port>`` of the egress proxy.
            host: the mail relay.
            port: its port.
            context: wraps the tunnel in implicit TLS checked against ``host``;
                None speaks plain SMTP through it.
        """
        self._egress_proxy = proxy
        self._implicit_tls = context
        super().__init__(host, port)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        from egress_connect import connect

        tunnel = connect(self._egress_proxy, host, port)
        if self._implicit_tls is None:
            return tunnel
        return self._implicit_tls.wrap_socket(tunnel, server_hostname=host)


def https_opener(context: ssl.SSLContext, proxy: str | None) -> Opener:
    """
    Args:
        context: see ``tls_context``.
        proxy: see ``https_connection``.
    """

    def send(
        method: str, url: str, body: bytes | None, headers: Mapping[str, str]
    ) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise ExportRefusedError(f"{parts.path} is no https:// URL")
        connection = https_connection(
            parts.hostname, parts.port or 443, context, 30, proxy
        )
        try:
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            connection.request(method, target, body=body, headers=dict(headers))
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    return send


def task_opener(environ: Mapping[str, str]) -> Opener:
    """
    Args:
        environ: the task environment, with ``BAO_CACERT`` under
            ``self_signed`` and ``EGRESS_PROXY`` on the export runner.
    """
    return https_opener(
        tls_context(environ.get("BAO_CACERT") or None),
        environ.get(PROXY_ENV) or None,
    )


def bao_client(environ: Mapping[str, str]) -> OpenBaoClient:
    """
    Args:
        environ: see ``task_opener``.

    Returns:
        A client of ``BAO_ADDR`` without a token yet.
    """
    return OpenBaoClient(
        environ.get("BAO_ADDR", ""),
        environ.get("BAO_CACERT") or None,
        None,
        proxy=environ.get(PROXY_ENV) or None,
    )


def now_ms() -> int:
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)


def iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).isoformat(timespec="seconds")


def membership_path(organization: str, group: str, user: str) -> str:
    return f"organizations/{organization}/groups/{group}/members/{user}"


def newest_membership(
    events: list[Mapping[str, Any]], path: str
) -> Mapping[str, Any] | None:
    matching = [
        event
        for event in events
        if event.get("resourceType") == MEMBERSHIP_TYPE
        and event.get("resourcePath") == path
    ]
    return max(matching, key=lambda event: int(event.get("time", 0)), default=None)


def recent_join(
    events: list[Mapping[str, Any]], path: str, now: int, min_age_days: int
) -> int | None:
    """
    Args:
        events: the admin events of the realm for the membership path.
        path: see ``membership_path``.
        now: the current time in epoch milliseconds.
        min_age_days: ``owner_min_age_days``.

    Returns:
        The time of the newest membership event in epoch milliseconds while
        it is a ``CREATE`` younger than the minimum age, else None; no event in
        the kept window means an older membership.
    """
    newest = newest_membership(events, path)
    if newest is None or newest.get("operationType") != "CREATE":
        return None
    joined = int(newest["time"])
    return joined if now - joined < min_age_days * DAY_MS else None


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def presign(
    method: str,
    url: str,
    credentials: Mapping[str, str],
    region: str,
    now: dt.datetime,
    expires: int,
    query: Mapping[str, str],
) -> str:
    """
    Args:
        method: the HTTP method the signature covers.
        url: the bucket or object URL without a query.
        credentials: ``access_key`` and ``secret_key`` of the S3 identity.
        region: the S3 region.
        now: the signing time.
        expires: the seconds the URL stays valid.
        query: the request parameters the signature covers beside its own.

    Returns:
        The URL with a SigV4 query signature over an unsigned payload.
    """
    parts = urllib.parse.urlsplit(url)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    scope = f"{now:%Y%m%d}/{region}/s3/aws4_request"
    params = {
        **query,
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{credentials['access_key']}/{scope}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    encoded = "&".join(
        f"{urllib.parse.quote(key, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}"
        for key, value in sorted(params.items())
    )
    canonical = "\n".join(
        (
            method,
            parts.path,
            encoded,
            f"host:{parts.netloc}",
            "",
            "host",
            "UNSIGNED-PAYLOAD",
        )
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{digest}"
    key = f"AWS4{credentials['secret_key']}".encode()
    for part in (f"{now:%Y%m%d}", region, "s3", "aws4_request"):
        key = _sign(key, part)
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{url}?{encoded}&X-Amz-Signature={signature}"


class ExportTask:
    def __init__(
        self,
        environ: Mapping[str, str],
        required: tuple[str, ...],
        opener: Opener,
        bao: OpenBaoClient,
    ) -> None:
        """
        Args:
            environ: the task environment.
            required: every name the task needs ``environ`` to set.
            opener: sends one HTTPS request and answers its status and body.
            bao: a client of ``BAO_ADDR`` without a token yet.
        """
        missing = [name for name in required if not environ.get(name)]
        if missing:
            raise ExportRefusedError(f"the task environment lacks {', '.join(missing)}")
        malformed = [
            name
            for name in MAIL_FLAGS
            if name in required and environ[name] not in ("true", "false")
        ]
        if malformed:
            raise ExportRefusedError(
                f"{', '.join(malformed)} is neither true nor false"
            )
        self.env = environ
        self.opener = opener
        self.bao = bao
        self.kc_token = ""

    def _call(
        self, method: str, url: str, body: bytes | None, headers: Mapping[str, str]
    ) -> bytes:
        status, raw = self.opener(method, url, body, headers)
        if not 200 <= status < 300:
            path = urllib.parse.urlsplit(url).path
            raise ExportRefusedError(f"{method} {path} answered HTTP {status}")
        return raw

    def login(self, role: str) -> None:
        """
        Args:
            role: the role of ``auth/jwt-export`` the task token logs in to.
        """
        self.bao.login_jwt(LOGIN_MOUNT, role, self.env["SEMAPHORE_JWT"])

    def keycloak_login(self) -> None:
        client = self.bao.read_all(PLATFORM_MOUNT, KEYCLOAK_LOGIN_PATH)
        base = self.env["EXPORT_KEYCLOAK_URL"].rstrip("/")
        realm = self.env["EXPORT_KEYCLOAK_REALM"]
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
            }
        ).encode()
        raw = self._call(
            "POST",
            f"{base}/realms/{realm}/protocol/openid-connect/token",
            body,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.kc_token = json.loads(raw)["access_token"]

    def _admin(self, path: str, query: Mapping[str, str]) -> Any:
        base = self.env["EXPORT_KEYCLOAK_URL"].rstrip("/")
        url = f"{base}/admin/realms/{self.env['EXPORT_KEYCLOAK_REALM']}/{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        raw = self._call("GET", url, None, {"Authorization": f"Bearer {self.kc_token}"})
        return json.loads(raw or b"null")

    def organization(self, workspace: str) -> str:
        """
        Args:
            workspace: the workspace id.

        Returns:
            The Keycloak id of the one organization carrying its marker.
        """
        found = self._admin(
            "organizations", {"q": f"workspace.id:{workspace}", "exact": "true"}
        )
        if len(found) != 1:
            raise ExportRefusedError(
                "no single organization carries the workspace marker"
            )
        return str(found[0]["id"])

    def members(self, organization: str, group: str) -> list[Mapping[str, Any]]:
        """
        Args:
            organization: see ``organization``.
            group: the pinned ``Owner`` group id.

        Returns:
            The direct members of that group id, never one of a subgroup.
        """
        return self._admin(
            f"organizations/{organization}/groups/{group}/members", {"max": "1000"}
        )

    def user(self, user: str) -> Mapping[str, Any]:
        return self._admin(f"users/{user}", {})

    def membership_events(self, path: str) -> list[Mapping[str, Any]]:
        """
        Args:
            path: see ``membership_path``.
        """
        return self._admin(
            "admin-events",
            {"resourcePath": path, "resourceTypes": MEMBERSHIP_TYPE, "max": "1000"},
        )

    def mail(self, members: list[Mapping[str, Any]], subject: str, text: str) -> None:
        """
        Args:
            members: the Keycloak users the mail goes to.
            subject: its subject.
            text: its body.
        """
        message = EmailMessage()
        message["From"] = self.env["EXPORT_MAIL_FROM"]
        message["To"] = ", ".join(
            str(member["email"]) for member in members if member.get("email")
        )
        message["Subject"] = subject
        message.set_content(text)
        address = (self.env["EXPORT_MAIL_HOST"], int(self.env["EXPORT_MAIL_PORT"]))
        context = None
        if self.env["EXPORT_MAIL_TLS"] == "true":
            context = tls_context(self.env.get("BAO_CACERT") or None)
        proxy = self.env.get(PROXY_ENV)
        if proxy:
            connection = TunneledSMTP(proxy, *address, context)
        elif context is not None:
            connection = smtplib.SMTP_SSL(*address, context=context)
        else:
            connection = smtplib.SMTP(*address)
        with connection as smtp:
            if self.env["EXPORT_MAIL_AUTH"] == "true":
                login = self.bao.read_all(PLATFORM_MOUNT, MAIL_LOGIN_PATH)
                smtp.login(login["username"], login["password"])
            smtp.send_message(message)

    def s3_credentials(self) -> dict[str, Any]:
        return self.bao.read_all(PLATFORM_MOUNT, S3_LOGIN_PATH)

    def bucket_url(self) -> str:
        return f"{self.env['EXPORT_S3_ENDPOINT'].rstrip('/')}/{BUCKET}"
