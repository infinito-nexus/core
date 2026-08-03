from __future__ import annotations

VOLUME_GROW_BATCH = 7
VOLUME_SIZE_LIMIT_MB = 1024
MIN_FREE_SPACE_VOLUMES = 2


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
    reads the bucket as missing even though it exists.

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
