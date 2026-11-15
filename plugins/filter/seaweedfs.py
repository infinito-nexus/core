from __future__ import annotations

import json
import re
import secrets

from ansible.errors import AnsibleFilterError

VOLUME_GROW_BATCH = 7
VOLUME_SIZE_LIMIT_MB = 1024
MIN_FREE_SPACE_VOLUMES = 2
POLICY_VERSION = "2012-10-17"
ANONYMOUS_DENY_SID = "DenyAnonymousRead"
NO_SUCH_BUCKET_POLICY = "<Code>NoSuchBucketPolicy</Code>"
NO_SUCH_BUCKET = "<Code>NoSuchBucket</Code>"
_BUCKET_LIST_ENTRY = re.compile(r"(\S+)\tsize:")
_LISTED_KEY = re.compile(r"<Key>([^<]*)</Key>")
_LISTED_TRUNCATED = re.compile(r"<IsTruncated>\s*true\s*</IsTruncated>")
_VERSIONING_ENABLED = re.compile(r"<Status>\s*Enabled\s*</Status>")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_WORKSPACE_ID = re.compile(rf"^{_UUID}$")
_RECORD_FILE = re.compile(rf"^ws-({_UUID})\.json$")
ADMIN_IDENTITY = "admin"
ADMIN_ACTION = "Admin"
WORKSPACE_ACTIONS = ("Read", "Write", "List")
WORKSPACE_MAX_KEY = "services.seaweedfs.workspaces.max"
STATE_SUFFIX = ".tfstate"


def min_free_space():
    return f"{VOLUME_SIZE_LIMIT_MB * MIN_FREE_SPACE_VOLUMES}MiB"


def volume_slots(collections, workspaces):
    """Volume-slot ceiling for a server hosting *collections* buckets.

    Args:
        collections: number of buckets this server serves. Each bucket is a
            SeaweedFS collection, and the master grows a collection in batches
            of VOLUME_GROW_BATCH; the default collection takes one batch of its
            own, hence the +1.
        workspaces: the workspace bucket maximum; each workspace bucket grows
            one volume at a time and so reserves one slot.
    """
    return (int(collections) + 1) * VOLUME_GROW_BATCH + int(workspaces)


def seaweedfs_command(s3_config="", collections=None, workspaces=None):
    """Build the SeaweedFS all-in-one ``server`` command.

    Single source for the args shared by the standalone provider stack
    (``compose.yml.j2``) and the local sidecar (``service.yml.j2``).
    ``-ip=localhost`` is deliberate: the all-in-one server otherwise
    advertises the auto-detected swarm ingress IP, which is unreachable for
    gRPC and hangs ``weed shell`` during bucket provisioning.

    Args:
        s3_config: path to the mounted s3.json; appended as ``-s3.config``
            when truthy. The local sidecar passes ``""`` since it does not
            mount that config.
        collections: number of buckets this server serves, passed to
            :func:`volume_slots`. Required; without it the stock entrypoint
            injects ``-volume.max=0`` and derives the ceiling from free disk
            space instead.
        workspaces: the workspace bucket maximum, passed to
            :func:`volume_slots`. Required; the sidecar passes 0.
    """
    if collections is None:
        raise ValueError(
            "seaweedfs_command requires 'collections': the number of buckets "
            "this server serves (the standalone stack passes its consumer "
            "count, the sidecar passes 1)."
        )
    if workspaces is None:
        raise ValueError(
            "seaweedfs_command requires 'workspaces': the workspace bucket "
            f"maximum ({WORKSPACE_MAX_KEY} for the standalone stack, 0 for "
            "the sidecar)."
        )
    command = [
        "server",
        "-dir=/data",
        "-ip=localhost",
        "-ip.bind=0.0.0.0",
        f"-master.volumeSizeLimitMB={VOLUME_SIZE_LIMIT_MB}",
        f"-volume.max={volume_slots(collections, workspaces)}",
        f"-volume.minFreeSpace={min_free_space()}",
        "-filer",
        "-s3",
    ]
    if s3_config:
        command.append(f"-s3.config={s3_config}")
    return command


def seaweedfs_sidecar_script(bucket, s3_port, access_key, secret_key):
    """Build the ``sh -c`` bootstrap script for the embedded sidecar.

    The sidecar creates its consumer's bucket itself at startup because a
    swarm stack's converge gate blocks before any post-deploy task could
    create it, deadlocking consumers that hard-fail on a missing bucket
    (e.g. the OpenTalk controller). The stock entrypoint routes every argv
    through ``weed`` (``sh`` as a command would become ``weed sh``), so the
    template overrides it with ``sh -c``; the server itself is still
    launched via ``/entrypoint.sh`` to keep its /data chown, privilege
    drop, and default server args.

    The script must stay free of every shell ``$``: the compose and swarm
    render paths launder dollars differently (a ``$pid`` reached the
    container as ``""`` and crash-looped the sidecar on a sh syntax error).
    The bucket bootstrap therefore polls ``/status`` from a backgrounded
    subshell while ``exec`` makes the server PID 1; the poll loop dies with
    the container and readiness is gated by the consumer's bounded wait.

    The ``s3.configure`` grant is required since SeaweedFS 4.39: a server
    started without an ``-s3.config`` has zero identities, and ListBuckets
    then returns an empty list to the consumer's access key, so the consumer
    reads the bucket as missing even though it exists. ``WriteAcp`` is
    required since SeaweedFS 4.49: a PutObject carrying ``x-amz-acl`` is
    also authorized as s3:PutObjectAcl and answers AccessDenied without it.

    Args:
        bucket: consumer bucket name created idempotently at startup.
        s3_port: S3 API port polled via ``/status`` before bucket creation.
        access_key: consumer S3 access key granted access to the bucket.
        secret_key: consumer S3 secret key.
    """
    server = " ".join(seaweedfs_command(collections=1, workspaces=0))
    grant = (
        f"s3.configure -user {bucket} -access_key {access_key} "
        f"-secret_key {secret_key} -buckets {bucket} "
        f"-actions Read,Write,WriteAcp,List,Tagging -apply"
    )
    return (
        f"(until wget -q -O /dev/null http://127.0.0.1:{s3_port}/status; do sleep 2; done; "
        f"echo 's3.bucket.create -name {bucket}' | /usr/bin/weed shell -master=localhost:9333 || true; "
        f"echo '{grant}' | /usr/bin/weed shell -master=localhost:9333) & "
        f"exec /entrypoint.sh {server}"
    )


def seaweedfs_anonymous_deny_policy(bucket):
    """Build the bucket policy that denies every unsigned read of *bucket*.

    SeaweedFS honours a public-read object or bucket ACL on an unsigned read
    unless a bucket policy explicitly denies it first. A bare
    ``Principal: "*"`` deny would also hit the consumer's own signed and
    presigned requests; the ``Null`` condition on ``aws:username`` limits it to
    unsigned ones, because SeaweedFS derives that key from a signed caller's
    IAM user ARN and evaluates an unsigned request as principal ``*`` without
    it.

    Args:
        bucket: bucket the policy is attached to; scopes both the bucket ARN
            (listings) and its object ARNs (GET/HEAD).
    """
    return {
        "Version": POLICY_VERSION,
        "Statement": [
            {
                "Sid": ANONYMOUS_DENY_SID,
                "Effect": "Deny",
                "Principal": "*",
                "Action": ["s3:Get*", "s3:List*"],
                "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                "Condition": {"Null": {"aws:username": "true"}},
            }
        ],
    }


def seaweedfs_bucket_names(output):
    """Return the bucket names a ``weed shell`` ``s3.bucket.list`` printed.

    Args:
        output: stdout of the shell; every bucket line carries the name
            followed by a tab and its ``size:`` column, and the first one may
            follow the shell prompt on the same line.
    """
    return _BUCKET_LIST_ENTRY.findall(str(output))


def seaweedfs_stored_bucket_policy(output):
    """Return the policy SeaweedFS reports for a bucket.

    Args:
        output: stdout of the admin curl ``GET /<bucket>?policy`` run with
            ``-w '\\n%{http_code}'``: the response body, a newline, and the
            HTTP status.

    Returns:
        The stored policy document on HTTP 200, an empty dict on HTTP 404
        ``NoSuchBucketPolicy``, and ``None`` on every other answer, a missing
        bucket (``NoSuchBucket``) included.
    """
    body, _, status = str(output).rpartition("\n")
    if status == "200":
        return json.loads(body)
    if status == "404" and NO_SUCH_BUCKET_POLICY in body:
        return {}
    return None


def seaweedfs_bucket_policy_target(stored, bucket, public):
    """Return the policy *bucket* converges to.

    Every statement except ``DenyAnonymousRead`` is kept as stored; that one
    is replaced by the current :func:`seaweedfs_anonymous_deny_policy`
    statement on a private bucket and dropped on a public one.

    Args:
        stored: policy document the bucket carries, an empty dict for none.
        bucket: bucket the deny statement scopes.
        public: whether the consumer is marked public; must be a bool.

    Returns:
        The target policy document, or an empty dict when no statement
        remains and the bucket must carry no policy.
    """
    if not isinstance(public, bool):
        raise AnsibleFilterError(
            f"seaweedfs_bucket_policy_target: public must be a bool, got {public!r}"
        )
    statements = [
        statement
        for statement in stored.get("Statement", [])
        if statement.get("Sid") != ANONYMOUS_DENY_SID
    ]
    if not public:
        statements.extend(seaweedfs_anonymous_deny_policy(bucket)["Statement"])
    if not statements:
        return {}
    return {"Version": POLICY_VERSION, "Statement": statements}


def _workspace_id(workspace):
    text = str(workspace)
    if not _WORKSPACE_ID.match(text):
        raise AnsibleFilterError(
            f"seaweedfs: the workspace id {workspace!r} is not a lowercase UUID"
        )
    return text


def seaweedfs_workspace(workspace):
    """Return the SeaweedFS names of one workspace.

    Args:
        workspace: the workspace id, a lowercase UUID.

    Returns:
        A dict with ``bucket`` (``ws-<id>-state``), ``identity``
        (``ws-<id>-provision``) and ``file`` (``ws-<id>.json``, its record in
        ``identities.d``).
    """
    workspace = _workspace_id(workspace)
    return {
        "bucket": f"ws-{workspace}-state",
        "identity": f"ws-{workspace}-provision",
        "file": f"ws-{workspace}.json",
    }


def seaweedfs_workspace_credentials(workspace):
    """Generate the S3 keys of a workspace identity that has none yet.

    Args:
        workspace: the workspace id, a lowercase UUID.

    Returns:
        The ``identities.d`` record: ``workspace``, ``access_key`` and
        ``secret_key``.
    """
    return {
        "workspace": _workspace_id(workspace),
        "access_key": secrets.token_hex(10).upper(),
        "secret_key": secrets.token_urlsafe(30),
    }


def _workspace_record(record):
    if not isinstance(record, dict) or set(record) != {
        "workspace",
        "access_key",
        "secret_key",
    }:
        raise AnsibleFilterError(
            "seaweedfs: an identities.d record holds exactly workspace, "
            "access_key and secret_key"
        )
    for field in ("access_key", "secret_key"):
        if not isinstance(record[field], str) or not record[field]:
            raise AnsibleFilterError(
                f"seaweedfs: the {field} of workspace {record['workspace']!r} is empty"
            )
    _workspace_id(record["workspace"])
    return record


def seaweedfs_workspace_identity(record):
    """Build the S3 identity of one workspace from its ``identities.d`` record.

    Args:
        record: the workspace's record, see :func:`seaweedfs_workspace_credentials`.

    Returns:
        The identity ``ws-<id>-provision`` with exactly ``Read``, ``Write``
        and ``List`` on the bucket ``ws-<id>-state``.
    """
    record = _workspace_record(record)
    names = seaweedfs_workspace(record["workspace"])
    return {
        "name": names["identity"],
        "credentials": [
            {"accessKey": record["access_key"], "secretKey": record["secret_key"]}
        ],
        "actions": [f"{action}:{names['bucket']}" for action in WORKSPACE_ACTIONS],
    }


def seaweedfs_s3_identities(identities, records):
    """Assemble the ``s3.json`` document the gateway loads.

    Args:
        identities: the inventory identities ``s3.json.j2`` renders; they
            MUST hold the identity ``admin`` with the ``Admin`` action and a
            key, so the gateway never runs without an identity.
        records: the ``identities.d`` records, one per workspace.

    Returns:
        The ``s3.json`` document: the inventory identities, then one identity
        per workspace in workspace id order.
    """
    inventory = list(identities)
    if not any(
        identity.get("name") == ADMIN_IDENTITY
        and ADMIN_ACTION in identity.get("actions", [])
        and identity.get("credentials")
        for identity in inventory
    ):
        raise AnsibleFilterError(
            "seaweedfs: the S3 identities hold no admin identity with the Admin "
            "action; a gateway without identities allows every request"
        )
    workspaces = sorted(
        (seaweedfs_workspace_identity(record) for record in records),
        key=lambda identity: identity["name"],
    )
    assembled = inventory + workspaces
    names = [identity.get("name") for identity in assembled]
    keys = [
        credential.get("accessKey")
        for identity in assembled
        for credential in identity.get("credentials", [])
    ]
    repeated = sorted({str(name) for name in names if names.count(name) > 1})
    if repeated:
        raise AnsibleFilterError(
            f"seaweedfs: the S3 identities repeat the name {', '.join(repeated)}"
        )
    if len(set(keys)) != len(keys):
        raise AnsibleFilterError("seaweedfs: two S3 identities share one access key")
    return {"identities": assembled}


def seaweedfs_workspace_slot(records, workspace, maximum):
    """Refuse a new workspace once every workspace slot is taken.

    Args:
        records: the file names in ``identities.d``, one ``ws-<id>.json`` per
            workspace that holds a slot.
        workspace: the workspace being applied.
        maximum: the value of ``services.seaweedfs.workspaces.max``.

    Returns:
        True when the workspace already holds a slot or a slot is free.
    """
    workspace = _workspace_id(workspace)
    if isinstance(maximum, bool):
        raise AnsibleFilterError(
            f"seaweedfs: {WORKSPACE_MAX_KEY} must be a number, got {maximum!r}"
        )
    taken = set()
    for name in records:
        match = _RECORD_FILE.match(str(name).rsplit("/", 1)[-1])
        if not match:
            raise AnsibleFilterError(
                f"seaweedfs: identities.d holds {name!r}, which names no workspace"
            )
        taken.add(match.group(1))
    if workspace in taken or len(taken) < int(maximum):
        return True
    raise AnsibleFilterError(
        f"seaweedfs: workspace {workspace} finds all {int(maximum)} workspace "
        f"slots taken; raise {WORKSPACE_MAX_KEY} to admit another workspace"
    )


def seaweedfs_location_configured(output, prefix, growth):
    """Return whether the filer configuration holds a location rule.

    Args:
        output: stdout of ``weed shell`` running ``fs.configure`` without
            ``-apply``: the filer configuration as JSON between the prompts.
        prefix: the ``locationPrefix`` the rule must carry.
        growth: the ``volumeGrowthCount`` the rule must carry.
    """
    text = str(output)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise AnsibleFilterError(
            "seaweedfs: fs.configure printed no filer configuration"
        )
    configuration = json.loads(text[start : end + 1])
    return any(
        location.get("locationPrefix") == prefix
        and int(location.get("volumeGrowthCount", 0)) == int(growth)
        for location in configuration.get("locations", [])
    )


def _status_split(output, request):
    body, _, status = str(output).rpartition("\n")
    if status not in ("200", "404"):
        raise AnsibleFilterError(
            f"seaweedfs: {request} answered HTTP {status or 'nothing'}"
        )
    return body, status


def seaweedfs_versioning_enabled(output):
    """Return whether ``GetBucketVersioning`` reports ``Enabled``.

    Args:
        output: stdout of the admin curl ``GET /<bucket>?versioning`` run with
            ``-w '\\n%{http_code}'``.
    """
    body, status = _status_split(output, "GetBucketVersioning")
    if status != "200":
        raise AnsibleFilterError(
            "seaweedfs: GetBucketVersioning found no bucket to report on"
        )
    return bool(_VERSIONING_ENABLED.search(body))


def seaweedfs_bucket_state_files(output):
    """Return the OpenTofu state files a bucket still holds.

    Args:
        output: stdout of the admin curl ``GET /<bucket>?list-type=2`` run
            with ``-w '\\n%{http_code}'``.

    Returns:
        The sorted keys that end in ``.tfstate``, empty when the bucket does
        not exist. A truncated listing is refused, because a state file could
        hide behind its end.
    """
    body, status = _status_split(output, "ListObjectsV2")
    if status == "404":
        if NO_SUCH_BUCKET in body:
            return []
        raise AnsibleFilterError(
            "seaweedfs: ListObjectsV2 answered HTTP 404 without NoSuchBucket"
        )
    if _LISTED_TRUNCATED.search(body):
        raise AnsibleFilterError(
            "seaweedfs: the bucket listing is truncated, so it cannot prove "
            "that no state file is left"
        )
    return sorted(
        key for key in _LISTED_KEY.findall(body) if key.endswith(STATE_SUFFIX)
    )


class FilterModule:
    def filters(self):
        return {
            "seaweedfs_bucket_names": seaweedfs_bucket_names,
            "seaweedfs_bucket_policy_target": seaweedfs_bucket_policy_target,
            "seaweedfs_bucket_state_files": seaweedfs_bucket_state_files,
            "seaweedfs_command": seaweedfs_command,
            "seaweedfs_location_configured": seaweedfs_location_configured,
            "seaweedfs_s3_identities": seaweedfs_s3_identities,
            "seaweedfs_sidecar_script": seaweedfs_sidecar_script,
            "seaweedfs_stored_bucket_policy": seaweedfs_stored_bucket_policy,
            "seaweedfs_versioning_enabled": seaweedfs_versioning_enabled,
            "seaweedfs_workspace": seaweedfs_workspace,
            "seaweedfs_workspace_credentials": seaweedfs_workspace_credentials,
            "seaweedfs_workspace_identity": seaweedfs_workspace_identity,
            "seaweedfs_workspace_slot": seaweedfs_workspace_slot,
        }
