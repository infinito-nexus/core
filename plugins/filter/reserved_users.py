import re

from ansible.errors import AnsibleFilterError


def reserved_usernames(users_dict):
    """
    Return a list of usernames where reserved: true.
    Usernames are regex-escaped to be safely embeddable.
    """
    if not isinstance(users_dict, dict):
        raise AnsibleFilterError("reserved_usernames expects a dictionary.")

    results = []

    for user in users_dict.values():
        if not isinstance(user, dict):
            continue
        if not user.get("reserved", False):
            continue
        username = user.get("username")
        if username:
            results.append(re.escape(str(username)))

    return results


def non_reserved_users(users_dict):
    """
    Return a dict of users where reserved != true.
    """
    if not isinstance(users_dict, dict):
        raise AnsibleFilterError("non_reserved_users expects a dictionary.")

    results = {}

    for key, user in users_dict.items():
        if not isinstance(user, dict):
            continue
        if user.get("reserved", False):
            continue
        results[key] = user

    return results


class FilterModule:
    """User filters for extracting reserved and non-reserved subsets."""

    def filters(self):
        return {
            "reserved_usernames": reserved_usernames,
            "non_reserved_users": non_reserved_users,
        }
