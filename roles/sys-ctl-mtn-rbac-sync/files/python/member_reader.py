import base64

from ldap_client import SCOPE_ONE_LEVEL, equality, present, raw

USERS_ROLE = "@users"


def first(values):
    """Args:
        values: the attribute values, possibly missing.

    Returns:
        The first value of the attribute, or an empty string.
    """
    return str(values[0]) if values else ""


def first_encoded(values):
    """Args:
        values: the attribute values ``parse_entry`` decoded, possibly missing.

    Returns:
        The octets of the first value base64-encoded, or an empty string.
    """
    return base64.b64encode(raw(values[0])).decode("ascii") if values else ""


def declared_attributes(hook):
    """Args:
        hook: the parsed hook; ``attributes`` lists the further directory
            attributes its members carry.

    Returns:
        The attribute names, empty for none.
    """
    return hook.get("attributes", [])


def role_group(application_id, role):
    """Args:
        application_id: the hook's application.
        role: a role of that application, ``@users``, or the group path
            ``/<root>/<application>/<role>`` of a role of any application.

    Returns:
        ``(application, role)`` of the directory group that holds the role's
        members.
    """
    if "/" not in role:
        return application_id, role
    segments = role.strip("/").split("/")
    if len(segments) != 3:
        raise ValueError(f"{role!r} is no group path /<root>/<application>/<role>")
    return segments[1], segments[2]


def users_holding(role, login):
    """Args:
        role: a role of a hook.
        login: the login attribute, held by every account.

    Returns:
        The attribute every account of a users role holds: the login for
        ``@users``, the named one for ``@users:<attribute>``; an empty string for
        any other role.
    """
    base, _, attribute = role.partition(":")
    if base != USERS_ROLE:
        return ""
    return attribute or login


def directory_members(connection, ldap, application_id, role, extra):
    """Args:
        connection: an open ``ldap_client.Connection``.
        ldap: the ``ldap`` block of ``config.json``.
        application_id: the application the role belongs to.
        role: the role name; ``@users`` stands for every account of the users OU,
            ``@users:<attribute>`` for every account of it that holds the attribute.
        extra: further attributes every member carries base64-encoded under
            ``attributes``; empty for none, and then members carry no such map.

    Returns:
        The accounts of the role, shaped like ``rbac_ldap_members``, each with the
        first value of every attribute.
    """
    attributes = ldap["attributes"]
    holding = users_holding(role, attributes["id"])
    if holding:
        search_filter = present(holding)
    else:
        search_filter = equality(
            attributes["member_of"], f"cn={application_id}-{role},{ldap['roles_dn']}"
        )
    entries = connection.search(
        ldap["users_dn"],
        SCOPE_ONE_LEVEL,
        search_filter,
        [
            attributes["id"],
            attributes["mail"],
            attributes["name"],
            attributes["uuid"],
            *extra,
        ],
    )
    members = []
    for _, values in entries:
        member = {
            "username": first(values.get(attributes["id"].lower())),
            "email": first(values.get(attributes["mail"].lower())),
            "name": first(values.get(attributes["name"].lower())),
            "uuid": first(values.get(attributes["uuid"].lower())),
        }
        if extra:
            member["attributes"] = {
                name: first_encoded(values.get(name.lower())) for name in extra
            }
        members.append(member)
    return sorted(
        (member for member in members if member["username"]),
        key=lambda member: member["username"],
    )


def hook_members(connection, ldap, hook):
    """Args:
        connection: an open ``ldap_client.Connection``.
        ldap: the ``ldap`` block of ``config.json``.
        hook: the parsed hook.

    Returns:
        ``{role: [members]}`` of every role of the hook, read from the directory.
    """
    return {
        role: directory_members(
            connection,
            ldap,
            *role_group(hook["application_id"], role),
            declared_attributes(hook),
        )
        for role in hook["roles"]
    }
