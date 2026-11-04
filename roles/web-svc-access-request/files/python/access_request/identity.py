"""The signed-in user, read only from the headers the SSO gate sets.

nginx strips every identity header a client sends and the oauth2-proxy gate in
front of the service sets them from its session, so these headers are the only
source of who is asking. Nothing a form submits names the requester.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import TYPE_CHECKING, Any

from .store import Person

if TYPE_CHECKING:
    from collections.abc import Mapping

USERNAME_HEADER = "X-Forwarded-Preferred-Username"
EMAIL_HEADER = "X-Forwarded-Email"
GROUPS_HEADER = "X-Forwarded-Groups"
FORWARDED_ACCESS_HEADER = "X-Forwarded-Access-Token"


class IdentityError(Exception):
    """The request carries no usable SSO session."""


def _claims(token: str) -> dict[str, Any]:
    """Return the payload of a JWT without checking its signature.

    The gate validated the session the token belongs to; Keycloak checks the
    signature itself whenever the service presents the token.

    Args:
        token: the access token of the session.
    """
    try:
        payload = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except (IndexError, ValueError, binascii.Error) as error:
        raise IdentityError("access token is not a JWT") from error
    if not isinstance(claims, dict):
        raise IdentityError("access token payload is not an object")
    return claims


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value).strip()
    return ""


def session_person(headers: Mapping[str, str]) -> Person:
    """Return the signed-in user of a request.

    Args:
        headers: the request headers.

    Raises:
        IdentityError: the gate set no access token, or the token names no
            subject or username.
    """
    token = _header(headers, FORWARDED_ACCESS_HEADER)
    if not token:
        raise IdentityError("no access token forwarded by the SSO gate")
    claims = _claims(token)
    sub = str(claims.get("sub") or "").strip()
    username = _header(headers, USERNAME_HEADER) or str(
        claims.get("preferred_username") or ""
    )
    if not sub or not username:
        raise IdentityError("session names no subject or username")
    groups = tuple(
        sorted(
            {
                "/" + group.strip().lstrip("/")
                for group in _header(headers, GROUPS_HEADER).split(",")
                if group.strip()
            }
        )
    )
    return Person(
        sub=sub,
        username=username,
        email=_header(headers, EMAIL_HEADER) or str(claims.get("email") or ""),
        groups=groups,
    )


def session_token(headers: Mapping[str, str]) -> str:
    """Return the access token of the signed-in user.

    Args:
        headers: the request headers.

    Raises:
        IdentityError: the gate set no access token.
    """
    token = _header(headers, FORWARDED_ACCESS_HEADER)
    if not token:
        raise IdentityError("no access token forwarded by the SSO gate")
    return token


def request_form(fields: Mapping[str, list[str]]) -> dict[str, Any]:
    """Return the parts of a submitted request form the service reads.

    Args:
        fields: parsed form fields, each name mapped to its values. A
            requester, username or e-mail field is ignored: the session
            names the requester.

    Returns:
        ``application``, the selected ``roles`` and the ``reason``.
    """
    return {
        "application": (fields.get("application") or [""])[0].strip(),
        "roles": [r.strip() for r in fields.get("roles") or [] if r.strip()],
        "reason": (fields.get("reason") or [""])[0],
    }
