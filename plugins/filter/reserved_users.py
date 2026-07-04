import re

from ansible.errors import AnsibleFilterError


def _accounts(user):
    accounts = user.get("accounts", [])
    if not isinstance(accounts, (list, tuple)):
        raise AnsibleFilterError("accounts must be a list.")
    return accounts


def reserved_usernames(users_dict):
    """
    Return the list of usernames that do NOT have an identity-directory account
    (``identity`` not in ``accounts``). These names are blocked from being
    registered as Keycloak usernames. Usernames are regex-escaped so the result
    is safe to embed in a deny pattern.
    """
    if not isinstance(users_dict, dict):
        raise AnsibleFilterError("reserved_usernames expects a dictionary.")

    results = []

    for user in users_dict.values():
        if not isinstance(user, dict):
            continue
        if "identity" in _accounts(user):
            continue
        username = user.get("username")
        if username:
            results.append(re.escape(str(username)))

    return results


def non_reserved_users(users_dict):
    """
    Return the subset of users that have an identity-directory account
    (``identity`` in ``accounts``). This is the set Keycloak/LDAP manage.
    """
    if not isinstance(users_dict, dict):
        raise AnsibleFilterError("non_reserved_users expects a dictionary.")

    results = {}

    for key, user in users_dict.items():
        if not isinstance(user, dict):
            continue
        if "identity" in _accounts(user):
            results[key] = user

    return results


class FilterModule:
    """User filters for identity-directory subsets and reserved usernames."""

    def filters(self):
        return {
            "reserved_usernames": reserved_usernames,
            "non_reserved_users": non_reserved_users,
        }
