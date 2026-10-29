from __future__ import annotations

import json
import re

from ansible.errors import AnsibleFilterError

VOLUME_GROW_BATCH = 7
VOLUME_SIZE_LIMIT_MB = 1024
MIN_FREE_SPACE_VOLUMES = 2
POLICY_VERSION = "2012-10-17"
ANONYMOUS_DENY_SID = "DenyAnonymousRead"
NO_SUCH_BUCKET_POLICY = "<Code>NoSuchBucketPolicy</Code>"
_BUCKET_LIST_ENTRY = re.compile(r"(\S+)\tsize:")


def min_free_space():
    return f"{VOLUME_SIZE_LIMIT_MB * MIN_FREE_SPACE_VOLUMES}MiB"


def volume_slots(collections):
    """Volume-slot ceiling for a server hosting *collections* buckets.

    Args:
        collections: number of buckets this server serves. Each bucket is a
            SeaweedFS collection, and the master grows a collection in batches
            of VOLUME_GROW_BATCH; the default collection takes one batch of its
            own, hence the +1.
    """
    return (int(collections) + 1) * VOLUME_GROW_BATCH


def seaweedfs_command(s3_config="", collections=None):
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
    """
    if collections is None:
        raise ValueError(
            "seaweedfs_command requires 'collections': the number of buckets "
            "this server serves (the standalone stack passes its consumer "
            "count, the sidecar passes 1)."
        )
    command = [
        "server",
        "-dir=/data",
        "-ip=localhost",
        "-ip.bind=0.0.0.0",
        f"-master.volumeSizeLimitMB={VOLUME_SIZE_LIMIT_MB}",
        f"-volume.max={volume_slots(collections)}",
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
    server = " ".join(seaweedfs_command(collections=1))
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


class FilterModule:
    def filters(self):
        return {
            "seaweedfs_bucket_names": seaweedfs_bucket_names,
            "seaweedfs_bucket_policy_target": seaweedfs_bucket_policy_target,
            "seaweedfs_command": seaweedfs_command,
            "seaweedfs_sidecar_script": seaweedfs_sidecar_script,
            "seaweedfs_stored_bucket_policy": seaweedfs_stored_bucket_policy,
        }
