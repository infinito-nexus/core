from __future__ import annotations

import hashlib
import importlib
import secrets
import sys
from pathlib import Path

from monitoring.survey import ALIAS_PREFIX, SHARE, RefusalError, RunError, path_host

MOUNT = "platform"
CHECKMK_PATH = "monitoring/checkmk"
AGENT_KEY_SOURCE = "monitoring/agent-key"
FEDERATION_PATH = "monitoring/federation/{alias}/{host}"
INVENTORY_KEY_PATH = "monitoring/inventory/{alias}"
DIGEST_MOUNT = "monitoring"
DIGEST_PATH = "{alias}/federation/{host}"
RELEASED_PATH = "{alias}/released/{host}"
RELEASING_PATH = "{alias}/releasing/{host}"
DIGEST_FIELD = "federation_token_sha256"
AGENT_KEY_PATH = "{alias}/agent/{host}"
AGENT_KEY_FIELD = "public_key"
TOKEN_BYTES = 32
HTTP_PRESENT = 200
HTTP_ABSENT = 404
DNS_ZONE_FIELD = "dns_zone"
LABEL_PATH = "{alias}/labels/{label}"
LABELS_PATH = "{alias}/labels/"
LABEL_FIELD = "host"


def openbao(env):
    """Returns:
    ``(error, client)``: the ``OpenBaoError`` of INFINITO_SRC_DIR and its
    ``OpenBaoClient`` holding the task's own token from BAO_TOKEN_FILE.
    """
    sys.path.insert(0, env["INFINITO_SRC_DIR"])
    module = importlib.import_module("utils.openbao_client")
    token = Path(env["BAO_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    return module.OpenBaoError, module.OpenBaoClient(
        env["BAO_ADDR"], env["BAO_CACERT"], token
    )


def bao_path(template, **segments):
    """Args:
    template: an OpenBao path template whose fields are ``PATH_SEGMENTS``
        kinds of ``utils/platform_monitoring.py``.
    segments: the value of each field, by kind.

    Returns:
        The path of :func:`utils.platform_monitoring.bao_path`.

    Raises:
        RunError: a value is no path segment of its kind, before any request.
    """
    try:
        return SHARE.bao_path(template, **segments)
    except ValueError as error:
        raise RunError(str(error)) from error


def _read(client, mount, path):
    """Args:
    client: an ``OpenBaoClient``.
    mount: a KV v2 mount.
    path: the secret's path below it.

    Returns:
        The secret's fields, also when it holds none, or None when OpenBao
        answers 404, so existence never depends on the content.

    Raises:
        RunError: any other answer, so a denied or failing read never passes
            as an absent secret.
    """
    status, body = client.request("GET", SHARE.bao_endpoint(mount, "data", path), None)
    if status == HTTP_ABSENT:
        return None
    if status != HTTP_PRESENT:
        raise RunError(f"reading {mount}/{path} answered {status}")
    return ((body or {}).get("data") or {}).get("data") or {}


def _fields(client, mount, path):
    return _read(client, mount, path) or {}


def _erase(client, mount, path):
    status, _ = client.request(
        "DELETE", SHARE.bao_endpoint(mount, "metadata", path), None
    )
    if status not in (200, 204, 404):
        raise RunError(f"erasing {mount}/{path} answered {status}")


def converge_secrets(client, planned, mint):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    planned: the result of ``plan``.
    mint: returns a fresh token.

    Returns:
        ``checkmk`` (``username``, ``secret``) and ``token``, MONITOR_HOST's
        federation token, None when it shares no Prometheus kind. A sharing
        host without one gets a new token at
        ``platform/monitoring/federation/<ws-id>/<host>``, which only this
        template reads, and its SHA-256 digest at
        ``monitoring/<ws-id>/federation/<host>`` (field
        ``federation_token_sha256``), which the workspace's deploy reads to
        guard ``/federate``; otherwise the token is erased and the digest
        dropped. ``apply`` records MONITOR_HOST as monitored at
        ``platform/monitoring/inventory/<ws-id>/hosts/<host>`` (field
        ``digest_files``, every file that deploy ever wrote the digest to,
        which :func:`workspace_digest_file` takes from the workspace's own
        core tree, so a core upgrade that moves the file keeps the old one
        on the list), a record the workspace reads but never writes or
        deletes, so ``release`` knows whether the host ever held a share and
        which files to remove; ``remove`` keeps it and only workspace destroy
        erases it. An agent host gets the platform monitoring public key of
        ``platform/monitoring/agent-key`` mirrored to
        ``monitoring/<ws-id>/agent/<host>`` (field ``public_key``), which
        the workspace's deploy reads for that host alone; any other host,
        and ``remove``, has it erased, as ``release`` erases it. ``apply``
        refuses a host the workspace released or claimed for a release
        (:func:`released_refusal`), checks so again after its platform
        record is written, so a release that claimed the host before it read
        that record is never passed, and binds DNS_LABEL to MONITOR_HOST at
        ``monitoring/<ws-id>/labels/<label>`` first, create-only, so of two
        concurrent applies for different hosts one refuses before any other
        write (:func:`label_refusal`); ``remove``, which runs after
        the Checkmk removal, erases every binding naming MONITOR_HOST. No
        other host's entry is touched; nothing is written when all hold.
    """
    alias, entry = planned["alias"], planned["entry"]
    host = path_host(planned["host"])
    token_path = bao_path(FEDERATION_PATH, alias=alias, host=host)
    digest_path = bao_path(DIGEST_PATH, alias=alias, host=host)
    mirror = bao_path(AGENT_KEY_PATH, alias=alias, host=host)
    monitored_path = bao_path(
        SHARE.MONITORED_PATH, workspace=alias.removeprefix(ALIAS_PREFIX), host=host
    )
    binding = (
        bao_path(LABEL_PATH, alias=alias, label=planned["label"])
        if planned.get("label")
        else None
    )
    digest_file = None
    if planned["action"] == "apply":
        released_refusal(client, planned)
        digest_file = workspace_digest_file(client, alias)
    token = None
    if binding and not client.write_create_only(
        DIGEST_MOUNT, binding, {LABEL_FIELD: planned["host"]}
    ):
        label_refusal(client, planned)
    if digest_file:
        held = _fields(client, MOUNT, monitored_path)
        files = sorted({*held.get(SHARE.DIGEST_FILES_FIELD, []), digest_file})
        if held != {SHARE.DIGEST_FILES_FIELD: files}:
            client.write(MOUNT, monitored_path, {SHARE.DIGEST_FILES_FIELD: files})
        if released(client, planned):
            unbind(client, planned)
            released_refusal(client, planned)
    if entry and entry["prometheus"]:
        token = _fields(client, MOUNT, token_path).get("token")
        if not token:
            token = mint()
            if not client.write_create_only(MOUNT, token_path, {"token": token}):
                raise RunError(f"the federation token of {host} appeared meanwhile")
        record = {DIGEST_FIELD: hashlib.sha256(token.encode()).hexdigest()}
    else:
        if _read(client, MOUNT, token_path) is not None:
            _erase(client, MOUNT, token_path)
        record = {}
    held = _read(client, DIGEST_MOUNT, digest_path)
    if record and held != record:
        client.write(DIGEST_MOUNT, digest_path, record)
    if not record and held is not None:
        _erase(client, DIGEST_MOUNT, digest_path)
    held = _read(client, DIGEST_MOUNT, mirror)
    if entry and entry["share"]["agent"]:
        public_key = client.read_all(MOUNT, AGENT_KEY_SOURCE)[AGENT_KEY_FIELD]
        if (held or {}).get(AGENT_KEY_FIELD) != public_key:
            client.write(DIGEST_MOUNT, mirror, {AGENT_KEY_FIELD: public_key})
    elif held is not None:
        _erase(client, DIGEST_MOUNT, mirror)
    if planned["action"] == "apply" and released(client, planned):
        for mount, path in (
            (MOUNT, token_path),
            (DIGEST_MOUNT, digest_path),
            (DIGEST_MOUNT, mirror),
        ):
            _erase(client, mount, path)
        unbind(client, planned)
        released_refusal(client, planned)
    if planned["action"] == "remove":
        folder = bao_path(LABELS_PATH, alias=alias)
        for label in client.list_tree(DIGEST_MOUNT, folder):
            binding = bao_path(LABEL_PATH, alias=alias, label=label)
            bound = _fields(client, DIGEST_MOUNT, binding).get(LABEL_FIELD)
            if bound == planned["host"]:
                _erase(client, DIGEST_MOUNT, binding)
    return {"checkmk": client.read_all(MOUNT, CHECKMK_PATH), "token": token}


def unbind(client, planned):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    planned: the result of ``plan``.

    Erases the DNS_LABEL binding of an apply a release claim stopped, when
    it names MONITOR_HOST, so a later host may take the label.
    """
    if not planned.get("label"):
        return
    binding = bao_path(LABEL_PATH, alias=planned["alias"], label=planned["label"])
    if _fields(client, DIGEST_MOUNT, binding).get(LABEL_FIELD) == planned["host"]:
        _erase(client, DIGEST_MOUNT, binding)


def released_refusal(client, planned):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    planned: the result of ``plan``.

    Raises:
        RefusalError: ``apply`` names a host whose release tombstone
            ``monitoring/<ws-id>/released/<host>`` or release claim
            ``monitoring/<ws-id>/releasing/<host>`` exists, whatever it holds,
            so a released or releasing host never gets an agent again and a
            refused login on a later ``release`` of that name stays proof of
            the earlier one.
    """
    if planned["action"] == "apply" and released(client, planned):
        raise RefusalError(
            f"host {planned['host']} was released in {planned['alias']}: use a"
            " new host name or destroy the workspace"
        )


def released(client, planned):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    planned: the result of ``plan``.

    Returns:
        Whether the release tombstone or the release claim of MONITOR_HOST
        exists, whatever it holds.
    """
    alias = planned["alias"]
    host = path_host(planned["host"])
    return any(
        _read(client, DIGEST_MOUNT, bao_path(template, alias=alias, host=host))
        is not None
        for template in (RELEASED_PATH, RELEASING_PATH)
    )


def workspace_digest_file(client, alias):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    alias: ``ws-<id>``.

    Returns:
        The federation digest file the core of the workspace's own runner
        image deploys, which ``workspace apply`` hands to OpenBao beside the
        inventory read key; the runner of this template may run another
        core.

    Raises:
        RefusalError: OpenBao holds none, an empty one, which the runner
            image of a core without platform monitoring gives, or one that
            is no digest file.
    """
    held = _fields(client, MOUNT, bao_path(INVENTORY_KEY_PATH, alias=alias))
    named = held.get(SHARE.DIGEST_FILE_FIELD)
    if named == "":
        raise RefusalError(
            f"the core of the runner of {alias} has no platform monitoring:"
            f" select a newer core for {alias.removeprefix(ALIAS_PREFIX)}"
        )
    if not SHARE.digest_file_path(named):
        raise RefusalError(
            f"OpenBao holds no federation digest file of {alias}: run workspace"
            f" apply for {alias.removeprefix(ALIAS_PREFIX)} first"
        )
    return named


def label_refusal(client, planned):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    planned: the result of ``plan``.

    Raises:
        RefusalError: the plan's DNS_LABEL is bound, at
            ``monitoring/<ws-id>/labels/<label>``, to another host than
            MONITOR_HOST by an earlier ``apply``, so one deploy name never
            monitors two hosts.
    """
    if not planned.get("label"):
        return
    path = bao_path(LABEL_PATH, alias=planned["alias"], label=planned["label"])
    bound = _fields(client, DIGEST_MOUNT, path).get(LABEL_FIELD)
    if bound and bound != planned["host"]:
        raise RefusalError(
            f"DNS_LABEL {planned['label']} is bound to host {bound}, not to"
            f" {planned['host']}"
        )


def inventory_key(client, workspace):
    """Args:
    client: an ``OpenBaoClient`` logged in as the ``monitoring`` role.
    workspace: the bare workspace id.

    Returns:
        ``(key, zone)``: the private read key and the DNS zone ``workspace
        apply`` handed to OpenBao; refuses when OpenBao holds either not.
    """
    alias = ALIAS_PREFIX + workspace
    held = _fields(client, MOUNT, bao_path(INVENTORY_KEY_PATH, alias=alias))
    for field, what in (
        ("private_key", "inventory read key"),
        (DNS_ZONE_FIELD, "DNS zone"),
    ):
        if not held.get(field):
            raise RefusalError(
                f"OpenBao holds no {what} of {alias}: "
                f"run workspace apply for {workspace} first"
            )
    return held["private_key"], held[DNS_ZONE_FIELD]


def mint_token():
    return secrets.token_urlsafe(TOKEN_BYTES)
