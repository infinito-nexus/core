"""The Checkmk agent of the platform monitoring share: its download URL, the
``authorized_keys`` line that runs it and the host key Checkmk pins."""

from __future__ import annotations

import base64
import binascii
import re

from .addresses import platform_address
from .hosts import DOMAIN
from .paths import PATH_SEGMENTS, SHA256, WORKSPACE_ID

SITE = re.compile(r"[a-z][a-z0-9_]{0,15}")
AGENT_COMMAND = "check_mk_agent"
AGENT_SECTION = "<<<infinito_workspace>>>"
AGENT_BINDING = "echo '{section}'; echo ws-{workspace}; exec "
AGENT_KEY_COMMENT = "infinito-platform-monitoring"
# Exception: the binding is optional, so a line written before the workspace binding existed still matches; a deploy rewrites it and a release removes it.
AGENT_KEY_PATTERN = (
    f'^command="(?:{AGENT_BINDING.format(section=AGENT_SECTION, workspace=WORKSPACE_ID)})?'
    f'{AGENT_COMMAND}",restrict,.* {AGENT_KEY_COMMENT}$'
)
KEY_TYPES = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
)
KEY_TYPE = "|".join(re.escape(name) for name in KEY_TYPES)
PUBLIC_KEY = re.compile(
    rf"^(?P<key>(?:{KEY_TYPE}) [A-Za-z0-9+/]+={{0,3}})(?: [^\r\n]*)?$"
)
HOST_KEY_VARIABLE = "ssh_host_key"
HOST_KEY = re.compile(rf"(?P<type>{KEY_TYPE}) (?P<blob>[A-Za-z0-9+/]+={{0,2}})")


def host_key_refusals(value, where):
    """Args:
        value: the ``ssh_host_key`` of one host, the OpenSSH host key line
            ``<type> <base64>`` Checkmk pins when it pulls the agent.
        where: the place ``value`` sits at, as the findings name it.

    Returns:
        One finding unless ``value`` is exactly one line of a ``KEY_TYPES``
        type and a base64 blob that decodes to a key of that same type: no
        options, no comment, no second line.
    """
    found = HOST_KEY.fullmatch(value) if isinstance(value, str) else None
    if found is not None:
        try:
            blob = base64.b64decode(found["blob"], validate=True)
        except binascii.Error:
            blob = b""
        size = int.from_bytes(blob[:4], "big")
        if blob[4 : 4 + size] == found["type"].encode():
            return []
    return [f"{where} is no OpenSSH host key line <{'|'.join(KEY_TYPES)}> <base64>"]


def agent_key_line(public_key, address, workspace):
    """Args:
        public_key: the platform monitoring public key, ``<type> <base64>``
            with an optional comment.
        address: the Checkmk host's address the key may log in from.
        workspace: the bare workspace id the deploy runs for.

    Returns:
        The ``authorized_keys`` line that lets the key run ``AGENT_COMMAND``
        and nothing else, from ``address`` only. The forced command first
        prints ``AGENT_SECTION`` and ``ws-<workspace>``, so the platform's
        ``infinito_agent_ssh`` drops the output of a host whose own deploy
        installed the line for another workspace than the Checkmk host it
        pulls for.

    Raises:
        ValueError: the key is no single OpenSSH key, the address is no
            plain IPv4 or IPv6 address or the workspace is no workspace id,
            each of which could smuggle options into the line.
    """
    found = PUBLIC_KEY.match(str(public_key).strip())
    if found is None:
        raise ValueError("the platform monitoring key is no OpenSSH public key")
    platform_address("PLATFORM_CHECKMK_ADDRESS", address)
    if not (
        isinstance(workspace, str) and PATH_SEGMENTS["workspace"].fullmatch(workspace)
    ):
        raise ValueError(f"WORKSPACE {workspace!r} is no workspace id")
    binding = AGENT_BINDING.format(section=AGENT_SECTION, workspace=workspace)
    return (
        f'command="{binding}{AGENT_COMMAND}",restrict,from="{address}" '
        f"{found['key']} {AGENT_KEY_COMMENT}"
    )


def agent_url(server, site, sha256):
    """Args:
        server: ``PLATFORM_CHECKMK_SERVER``, the platform's Checkmk domain.
        site: ``PLATFORM_CHECKMK_SITE``, its Checkmk site.
        sha256: ``PLATFORM_CHECKMK_AGENT_SHA256``, the digest of the agent
            script that site serves, which the download has to match.

    Returns:
        The HTTPS URL of the site's Linux agent script.

    Raises:
        ValueError: one value the platform injects into the workspace deploy
            is empty or malformed, so the deploy never fetches from a host or
            path it did not check.
    """
    if not (isinstance(server, str) and DOMAIN.fullmatch(server)):
        raise ValueError(f"PLATFORM_CHECKMK_SERVER {server!r} is no lowercase domain")
    if not (isinstance(site, str) and SITE.fullmatch(site)):
        raise ValueError(f"PLATFORM_CHECKMK_SITE {site!r} is no Checkmk site name")
    if not (isinstance(sha256, str) and SHA256.fullmatch(sha256)):
        raise ValueError("PLATFORM_CHECKMK_AGENT_SHA256 is no SHA-256 hex digest")
    return f"https://{server}/{site}/check_mk/agents/check_mk_agent.linux"
