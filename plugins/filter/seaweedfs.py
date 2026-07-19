from __future__ import annotations


def seaweedfs_command(s3_config=""):
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
    """
    command = [
        "server",
        "-dir=/data",
        "-ip=localhost",
        "-ip.bind=0.0.0.0",
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
    reads the bucket as missing even though it exists.

    Args:
        bucket: consumer bucket name created idempotently at startup.
        s3_port: S3 API port polled via ``/status`` before bucket creation.
        access_key: consumer S3 access key granted access to the bucket.
        secret_key: consumer S3 secret key.
    """
    server = " ".join(seaweedfs_command())
    grant = (
        f"s3.configure -user {bucket} -access_key {access_key} "
        f"-secret_key {secret_key} -buckets {bucket} "
        f"-actions Read,Write,List,Tagging -apply"
    )
    return (
        f"(until wget -q -O /dev/null http://127.0.0.1:{s3_port}/status; do sleep 2; done; "
        f"echo 's3.bucket.create -name {bucket}' | /usr/bin/weed shell -master=localhost:9333 || true; "
        f"echo '{grant}' | /usr/bin/weed shell -master=localhost:9333) & "
        f"exec /entrypoint.sh {server}"
    )


class FilterModule:
    def filters(self):
        return {
            "seaweedfs_command": seaweedfs_command,
            "seaweedfs_sidecar_script": seaweedfs_sidecar_script,
        }
