"""OpenBao paths and the federation digest file of the platform monitoring
share."""

from __future__ import annotations

import re
from urllib.parse import quote

from .hosts import HOST_LABEL, host_segment

DIGEST_FILE = "federate.sha256"
DIGEST_MOUNT = "monitoring"
DIGEST_PATH = "ws-{workspace}/federation/{host}"
DIGEST_REFERENCE = f"{DIGEST_MOUNT}/{DIGEST_PATH}#federation_token_sha256"
DIGEST_FILE_FIELD = "digest_file"
DIGEST_FILE_PATH = re.compile(rf"(/[A-Za-z0-9._-]+)*/{re.escape(DIGEST_FILE)}")
DIGEST_FILES_FIELD = "digest_files"
MARKER_PATH = "ws-{workspace}/released/{host}"
CLAIM_PATH = "ws-{workspace}/releasing/{host}"
AGENT_KEY_PATH = "ws-{workspace}/agent/{host}"
AGENT_KEY_REFERENCE = f"{DIGEST_MOUNT}/{AGENT_KEY_PATH}#public_key"
FEDERATION_MOUNT = "platform"
FEDERATION_PATH = "monitoring/federation/ws-{workspace}/{host}"
MONITORED_PATH = "monitoring/inventory/ws-{workspace}/hosts/{host}"
WORKSPACE_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PATH_SEGMENTS = {
    "workspace": re.compile(WORKSPACE_ID),
    "alias": re.compile(rf"ws-{WORKSPACE_ID}"),
    "host": re.compile(r"[a-z0-9_][a-z0-9._-]{0,252}"),
    "label": re.compile(HOST_LABEL),
}
SHA256 = re.compile(r"[0-9a-f]{64}")


def digest_path(configuration_base):
    """Args:
        configuration_base: ``directories.configuration.base`` of the nginx
            lookup, which openresty binds at the same path.

    Returns:
        The file holding the SHA-256 hex digest of the instance's federation
        token, which ``/federate`` reads on every request.
    """
    return f"{configuration_base.rstrip('/')}/{DIGEST_FILE}"


def digest_file_path(value):
    """Args:
        value: the ``digest_file`` a digest record names.

    Returns:
        Whether it is an absolute path of plain segments, none of them ``.``
        or ``..``, that ends in ``DIGEST_FILE``, so the release removes and
        checks that file alone and the path is safe in its command line.
    """
    if not isinstance(value, str) or not DIGEST_FILE_PATH.fullmatch(value):
        return False
    return not any(part in (".", "..") for part in value.split("/"))


def bao_path(template, **segments):
    """Args:
        template: an OpenBao path template whose fields are
            ``PATH_SEGMENTS`` kinds.
        segments: the value of each field, by kind.

    Returns:
        ``template`` with every value checked against its kind and quoted.

    Raises:
        ValueError: a value is no path segment of its kind, such as an
            empty one, ``.``, ``..`` or one holding ``/``, ``?``, ``#``,
            ``%`` or a control character.
    """
    for kind, value in segments.items():
        if not (isinstance(value, str) and PATH_SEGMENTS[kind].fullmatch(value)):
            raise ValueError(f"{value!r} is no OpenBao path segment of a {kind}")
    return template.format(
        **{kind: quote(value, safe="") for kind, value in segments.items()}
    )


def bao_endpoint(mount, kind, path):
    """Args:
        mount: a KV v2 mount.
        kind: ``data`` or ``metadata``.
        path: a path :func:`bao_path` built.

    Returns:
        The request path below ``/v1/``.
    """
    return f"{quote(mount, safe='')}/{kind}/{quote(path)}"


def digest_reference(workspace, host):
    """Args:
        workspace: the bare workspace id the deploy runs for.
        host: the inventory host name of the instance.

    Returns:
        The OpenBao reference of the digest the platform's ``monitoring``
        template writes next to the token it keeps, the host sanitised as
        that template sanitises it; the workspace deploy reads it from there.
    """
    return {
        "openbao": bao_path(
            DIGEST_REFERENCE, workspace=workspace, host=host_segment(host)
        )
    }


def agent_key_reference(workspace, host):
    """Args:
        workspace: the bare workspace id the deploy runs for.
        host: the inventory host name of the instance.

    Returns:
        The OpenBao reference of the platform monitoring public key the
        ``monitoring`` template mirrors for that host alone; the workspace
        deploy reads it from there. ``release`` and ``monitoring remove``
        erase it and ``monitoring apply`` refuses a released host, so no
        deploy of a released host finds the key again.
    """
    return {
        "openbao": bao_path(
            AGENT_KEY_REFERENCE, workspace=workspace, host=host_segment(host)
        )
    }


def digest_entry(digest, host):
    """Args:
        digest: the SHA-256 hex digest of the host's federation token.
        host: the inventory host the token belongs to.

    Returns:
        The line ``<host_segment> <digest>`` the digest file holds for the
        host. ``/federate`` admits a bearer whose digest any line holds, so
        every host of a stack keeps its own token, a deploy rewrites only its
        own line and a release removes only its own.

    Raises:
        ValueError: ``digest`` is no lowercase SHA-256 hex digest.
    """
    if not SHA256.fullmatch(str(digest)):
        raise ValueError("the federation token digest is no lowercase SHA-256 hex")
    return f"{host_segment(host)} {digest}"
