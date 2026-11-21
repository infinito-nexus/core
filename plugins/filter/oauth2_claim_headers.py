"""Filter that names the headers an oauth2-proxy gate forwards for ID token claims.

Example::

    {{ OIDC.ATTRIBUTES | oauth2_claim_headers(['NAME']) }}
    -> [{"key": "NAME", "claim": "name", "request": "X-Forwarded-Name",
         "response": "X-Auth-Request-Name",
         "variable": "upstream_http_x_auth_request_name"}]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

NOT_FORWARDABLE = frozenset({"USERNAME", "EMAIL", "ADDRESS"})


def _header(key: str) -> dict[str, str]:
    parts = key.lower().split("_")
    title = "-".join(part.capitalize() for part in parts)
    return {
        "request": f"X-Forwarded-{title}",
        "response": f"X-Auth-Request-{title}",
        "variable": "upstream_http_x_auth_request_" + "_".join(parts),
    }


def oauth2_claim_headers(
    attributes: Mapping[str, Any], declared: Iterable[str] | None = None
) -> list[dict[str, str]]:
    """Return the claim headers of the declared keys, or of every forwardable key.

    Args:
        attributes: ``OIDC.ATTRIBUTES``, mapping key to claim name.
        declared: ``OIDC.ATTRIBUTES`` keys an application forwards; every
            forwardable key when omitted.
    """
    forwardable = [key for key in attributes if key not in NOT_FORWARDABLE]
    keys = forwardable if declared is None else [str(key) for key in declared]
    unknown = sorted(set(keys) - set(forwardable))
    if unknown:
        raise AnsibleFilterError(
            f"oauth2_claim_headers: {unknown} are not forwardable OIDC.ATTRIBUTES keys; "
            f"choose from {sorted(forwardable)}"
        )
    return [{"key": key, "claim": str(attributes[key]), **_header(key)} for key in keys]


class FilterModule:
    def filters(self):
        return {"oauth2_claim_headers": oauth2_claim_headers}
