#!/usr/bin/env python3

# Provides a filter to control which applications (roles) should be deployed

from ansible.errors import AnsibleFilterError


def application_allowed(
    application_id: str, group_names: list, allowed_applications: list | None = None
):
    """
    Return True if:
      - application_id exists in group_names, AND
      - either allowed_applications is not provided (or empty), OR application_id is in allowed_applications.

    Parameters:
      application_id (str): Name of the application/role to check.
      group_names (list): List of groups the current host belongs to.
      allowed_applications (list, optional): List of application IDs to allow.

    Returns:
      bool: True if this application is allowed to deploy, False otherwise.
    """
    # Ensure group_names is iterable
    if allowed_applications is None:
        allowed_applications = []
    if not isinstance(group_names, (list, tuple)):
        raise AnsibleFilterError(
            f"Expected group_names to be a list, str or tuple, got {type(group_names)}"
        )

    # Must be part of the host's groups
    if application_id not in group_names:
        return False

    # If allowed_applications provided, only allow if ID is in that list
    if allowed_applications:
        if not isinstance(allowed_applications, (list, tuple, str)):
            raise AnsibleFilterError(
                f"allowed_applications must be a list or tuple if provided, got {type(allowed_applications)}"
            )
        return application_id in allowed_applications

    # No filter provided → allow all in group_names
    return True


class FilterModule:
    def filters(self):
        return {
            "application_allowed": application_allowed,
        }
