from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse

from provision import inputs
from provision.remote import (
    SYSTEM_TRUST,
    TIMEOUT,
    RemoteError,
    alarm_deferred,
    exchange,
)

REVOKE_TIMEOUT = 10
REFUSED_LOGIN = (401, 403)
REVOKED = (200, 204)


def _keystone_time(value):
    """Args:
        value: a Keystone time, ISO 8601 in UTC with or without a zone.

    Returns:
        The aware time, None when the value is no ISO 8601 time.
    """
    try:
        moment = dt.datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def contract_breach(token, record, deadline):
    """Args:
        token: the ``token`` of Keystone's answer to the application credential.
        record: the ``application_credential`` Keystone holds for it.
        deadline: the aware time the run's time budget ends at.

    Returns:
        The first rule of the contract the credential breaks, empty for none.
    """
    scope = token.get("project")
    project = scope.get("id") if isinstance(scope, dict) else None
    if not project or not record.get("project_id"):
        return "is scoped to no project"
    if project != record["project_id"] or "domain" in token or "system" in token:
        return "is scoped to more than one project"
    if record.get("unrestricted") is not False:
        return "is unrestricted, so it could create further credentials"
    if record.get("expires_at") is None:
        return ""
    expires = _keystone_time(record["expires_at"])
    if expires is None:
        return "names no readable expiry"
    if expires < deadline:
        return (
            f"expires at {expires.isoformat()}, before the run's time budget ends "
            f"at {deadline.isoformat()}"
        )
    return ""


def keystone_contract(auth_url, credential_id, secret, deadline):
    """Args:
        auth_url: the Keystone v3 endpoint of the catalog region.
        credential_id: the id of the customer's application credential.
        secret: its secret; it travels in the request body only, and no
            message names it.
        deadline: the aware time the run's time budget ends at.

    Raises:
        RefusedError: Keystone answers the login with 401 or 403, or the
            credential breaks a rule of :func:`contract_breach`; the message
            names the rule.
        RemoteError: any other answer, an answer without its document, or
            a token Keystone keeps after the check; the token minted for the
            check is revoked whether the check passes or refuses. When the
            check already raises, a failed revoke goes to stderr and the
            check's own error is raised.
    """
    base = auth_url.rstrip("/")
    host = urllib.parse.urlsplit(base).hostname
    body = {
        "auth": {
            "identity": {
                "methods": ["application_credential"],
                "application_credential": {"id": credential_id, "secret": secret},
            }
        }
    }
    status, headers, payload = exchange(
        f"{base}/auth/tokens",
        "POST",
        {"Accept": "application/json", "Content-Type": "application/json"},
        json.dumps(body).encode("utf-8"),
        SYSTEM_TRUST,
        TIMEOUT,
    )
    if status in REFUSED_LOGIN:
        raise inputs.RefusedError(
            f"the application credential does not authenticate at Keystone "
            f"{host}: HTTP {status}"
        )
    if status != 201:
        raise RemoteError(f"Keystone POST {host}/auth/tokens: HTTP {status}")
    subject = headers.get("x-subject-token")
    if not subject:
        raise RemoteError(f"Keystone {host} issued no token for the credential")
    try:
        token = _keystone_member(payload, "token", host)
        record = _own_record(base, host, token, credential_id, subject)
        breach = contract_breach(token, record, deadline)
    except BaseException:
        try:
            _revoke(base, host, subject)
        except Exception as failure:
            print(f"revoking the token of the failed check: {failure}", file=sys.stderr)
        raise
    _revoke(base, host, subject)
    if breach:
        raise inputs.RefusedError(f"the application credential {breach}")


def _keystone_member(payload, key, host):
    """Args:
        payload: the body of a Keystone answer.
        key: the member the answer must hold.
        host: the Keystone host an error names.

    Returns:
        That member; an answer without it raises :class:`RemoteError`.
    """
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RemoteError(f"Keystone {host} answered no JSON document") from None
    member = document.get(key) if isinstance(document, dict) else None
    if not isinstance(member, dict):
        raise RemoteError(f"Keystone {host} answered without {key}")
    return member


def _own_record(base, host, token, credential_id, subject):
    """Args:
        base: the Keystone v3 endpoint without a trailing slash.
        host: its host, which an error names.
        token: the ``token`` Keystone minted for the credential.
        credential_id: the id of the credential.
        subject: the minted token, sent as ``X-Auth-Token`` only.

    Returns:
        The ``application_credential`` Keystone holds for the credential.
    """
    user = token.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        raise RemoteError(f"Keystone {host} named no user for the token")
    path = "/".join(
        urllib.parse.quote(str(part), safe="")
        for part in ("users", user["id"], "application_credentials", credential_id)
    )
    status, _, payload = exchange(
        f"{base}/{path}",
        "GET",
        {"Accept": "application/json", "X-Auth-Token": subject},
        None,
        SYSTEM_TRUST,
        TIMEOUT,
    )
    if status != 200:
        raise RemoteError(f"Keystone {host} withheld the credential: HTTP {status}")
    return _keystone_member(payload, "application_credential", host)


def _revoke(base, host, subject):
    """Args:
    base: the Keystone v3 endpoint without a trailing slash.
    host: its host, which an error names.
    subject: the token minted for the check, revoked with itself.
    """
    with alarm_deferred():
        status, _, _ = exchange(
            f"{base}/auth/tokens",
            "DELETE",
            {"X-Auth-Token": subject, "X-Subject-Token": subject},
            None,
            SYSTEM_TRUST,
            REVOKE_TIMEOUT,
        )
    if status not in REVOKED:
        raise RemoteError(f"Keystone {host} kept the token of the check: HTTP {status}")
