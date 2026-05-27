from ansible.errors import AnsibleFilterError


def docker_volume_path(volume_name: str) -> str:
    """
    Returns the absolute filesystem path of a Docker volume.

    Example:
        "akaunting_data" -> "/var/lib/docker/volumes/akaunting_data/_data/"
    """
    if not volume_name or not isinstance(volume_name, str):
        raise AnsibleFilterError(f"Invalid volume name: {volume_name}")

    return f"/var/lib/docker/volumes/{volume_name}/_data/"


class FilterModule:
    """Docker volume path filters."""

    def filters(self):
        return {
            "docker_volume_path": docker_volume_path,
        }
