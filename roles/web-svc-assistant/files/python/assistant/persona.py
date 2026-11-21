"""Which persona answers a request, read only from the headers the SSO gate sets.

On a vhost the oauth2-proxy gate guards, openresty sets the identity headers
from the gate's session; on every other location it blanks them, so a client
cannot forge them. A request without a username is anonymous. The header names
and the group spelling are the ones ``web-svc-access-request`` reads.
"""

from __future__ import annotations

USERNAME_HEADER = "X-Forwarded-Preferred-Username"
GROUPS_HEADER = "X-Forwarded-Groups"

END_USER = "end-user-support"
CONSULTANT = "technical-consultant"


def _header(headers, name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value).strip()
    return ""


def normalised_group(group: str) -> str:
    """Return a group path in the ``/roles/<app>/<role>`` spelling.

    Args:
        group: a group path with or without its leading slash.
    """
    return "/" + group.strip().strip("/")


def signed_in(headers) -> bool:
    """Return whether the gate named a user for the request.

    Args:
        headers: the request headers.
    """
    return bool(_header(headers, USERNAME_HEADER))


def groups(headers) -> frozenset[str]:
    """Return the groups the gate listed for the signed-in user.

    Args:
        headers: the request headers.
    """
    if not signed_in(headers):
        return frozenset()
    return frozenset(
        normalised_group(group)
        for group in _header(headers, GROUPS_HEADER).split(",")
        if group.strip().strip("/")
    )


def persona(headers, admin_group: str) -> str:
    """Return the persona that answers the request.

    Args:
        headers: the request headers.
        admin_group: the RBAC group whose members get the technical consultant.
    """
    if normalised_group(admin_group) in groups(headers):
        return CONSULTANT
    return END_USER
