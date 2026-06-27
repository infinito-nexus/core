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


class FilterModule:
    def filters(self):
        return {
            "seaweedfs_command": seaweedfs_command,
        }
