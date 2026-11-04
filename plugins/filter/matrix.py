"""Build the Matrix identifiers whose shape several templates repeat.

A Matrix user id is ``@<localpart>:<server_name>``. Six templates of
web-app-matrix assembled it by hand, which is how the MDAD flavor came to use a
different server name than the compose flavor. The shape lives here and the
server name stays in ``MATRIX_SERVER_NAME``, so a caller supplies only the
localpart and the homeserver it belongs to.
"""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

SIGIL = "@"
SEPARATOR = ":"
FORBIDDEN = (SIGIL, SEPARATOR, "/")


def mxid(localpart: str, server_name: str) -> str:
    """Return the Matrix user id of ``localpart`` on ``server_name``.

    Args:
        localpart: the user's name without sigil or server, e.g. ``alice``. A
            leading ``@`` is accepted and dropped so a caller may pass either.
        server_name: the homeserver's name, normally ``MATRIX_SERVER_NAME``.

    Returns:
        ``@<localpart>:<server_name>``, lowercased: Synapse rejects a user id
        that is not, and the callers read usernames from inventory.

    Raises:
        AnsibleFilterError: either part is empty, or the localpart still
            carries a sigil, a separator or a slash after the leading ``@``.
    """
    name = str(localpart or "").strip().removeprefix(SIGIL)
    server = str(server_name or "").strip()
    if not name:
        raise AnsibleFilterError("mxid: the localpart is empty")
    if not server:
        raise AnsibleFilterError(f"mxid: no server name for localpart '{name}'")
    bad = [character for character in FORBIDDEN if character in name]
    if bad:
        raise AnsibleFilterError(
            f"mxid: localpart '{name}' carries {' and '.join(bad)}; "
            "pass the bare name, not a user id"
        )
    return f"{SIGIL}{name}{SEPARATOR}{server}".lower()


class FilterModule:
    def filters(self):
        return {"mxid": mxid}
