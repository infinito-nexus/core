# Custom Ansible filter to generate service script paths.


def get_service_script_path(systemctl_id, script_type):
    """
    Build the path to a service script based on systemctl_id and type.

    :param systemctl_id: The identifier of the system service.
    :param script_type: The script type/extension (e.g., sh, py, yml).
    :return: The full path string.
    """
    if not systemctl_id or not script_type:
        raise ValueError("Both systemctl_id and script_type are required")

    return f"/opt/scripts/systemctl/{systemctl_id}/script.{script_type}"


class FilterModule:
    """Custom filters for Ansible"""

    def filters(self):
        return {"get_service_script_path": get_service_script_path}
