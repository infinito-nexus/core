# roles/common/filter_plugins/social.py
from ansible.errors import AnsibleFilterError


def fediverse_url(handle, protocol="https", path_prefix="@"):
    """
    Convert a Fediverse handle into a full profile URL.

    Examples:
      '@user@instance.tld' -> 'https://instance.tld/@user'
      'user@instance.tld'  -> 'https://instance.tld/@user'
    """
    if not handle:
        return ""

    value = str(handle).strip()

    # Optional leading '@'
    value = value.removeprefix("@")

    parts = value.split("@")
    if len(parts) != 2:
        raise AnsibleFilterError(f"Invalid Fediverse handle '{handle}'")

    username, host = parts
    username = username.strip()
    host = host.strip()

    if not username or not host:
        raise AnsibleFilterError(f"Invalid Fediverse handle '{handle}'")

    # Allow configurable path prefix, default "@"
    return f"{protocol}://{host}/{path_prefix}{username}"


class FilterModule:
    def filters(self):
        return {
            "fediverse_url": fediverse_url,
        }
